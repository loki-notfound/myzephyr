#!/usr/bin/env python3
"""Self-test of zephyrd-check.py. Tests the harness, not zephyrd.

  harness-selftest.py <work-dir>     (<work-dir> must not exist)

1. get_info assertions against fixed fixtures (valid and invalid answers).
2. Classification of later get_info samples, and Run.discovery driven by fixed
   in-memory RPC answers (no process, no network): valid progress passes; a later
   invalid answer fails however valid the first was; BUSY answers, RPC error
   objects and failed requests never contribute their heights.
3. Scenario runs with tests/stub-zephyrd.py: expected exit status, an upper bound
   on elapsed time, the child gone afterwards, no listener left on the test ports,
   the recorded checks where they matter, and an unrelated process that holds a
   test port left running.
Exit 0 when every case behaves as expected, 1 otherwise.
"""
import importlib.util
import io
import json
import types
import urllib.error
import os
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True  # never leave __pycache__ in the checkout
here = os.path.dirname(os.path.abspath(__file__))
check_py = os.path.join(os.path.dirname(here), "zephyrd-check.py")
stub = os.path.join(here, "stub-zephyrd.py")
spec = importlib.util.spec_from_file_location("zc", check_py)
zc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zc)

work = sys.argv[1] if len(sys.argv) == 2 else sys.exit("usage: harness-selftest.py <work-dir>")
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
PORTS = "28390,28391,28392"
failures = []
results = []


def record(name, ok, detail):
    results.append({"case": name, "ok": ok, "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")
    if not ok:
        failures.append(name)


# 1. assertion fixtures
def good(**over):
    r = {"status": "OK", "offline": True, "version": "2.3.0-release", "nettype": "mainnet",
         "mainnet": True, "height": 1, "outgoing_connections_count": 0}
    r.update(over)
    return {"jsonrpc": "2.0", "id": "0", "result": r}


fixtures = [
    ("valid offline answer", good(), "2.3.0-release", True, True),
    ("valid untagged version", good(version="2.3.0-8c6a12025"), "2.3.0-8c6a12025", True, True),
    ("status BUSY", good(status="BUSY"), "2.3.0-release", True, False),
    ("offline false when offline expected", good(offline=False), "2.3.0-release", True, False),
    ("offline missing", {"result": {k: v for k, v in good()["result"].items() if k != "offline"}}, "2.3.0-release", True, False),
    ("wrong version suffix", good(version="2.3.0-8c6a12025"), "2.3.0-release", True, False),
    ("malformed version", good(version="v2.3.0"), "2.3.0-release", True, False),
    ("testnet", good(nettype="testnet", mainnet=False), "2.3.0-release", True, False),
    ("height zero", good(height=0), "2.3.0-release", True, False),
    ("height as string", good(height="1"), "2.3.0-release", True, False),
    ("outgoing peers while offline", good(outgoing_connections_count=2), "2.3.0-release", True, False),
    ("RPC error object", {"jsonrpc": "2.0", "id": "0", "error": {"code": -1, "message": "x"}}, "2.3.0-release", True, False),
    ("result not an object", {"result": "OK"}, "2.3.0-release", True, False),
    ("not an object", ["OK"], "2.3.0-release", True, False),
    ("valid online answer", good(offline=False, outgoing_connections_count=3), "2.3.0-release", False, True),
]
for name, info, ver, offline, want_ok in fixtures:
    errs = zc.check_info(info, ver, offline)
    record(f"assert: {name}", (not errs) == want_ok, errs or "no problems")

conn_ok = {"result": {"status": "OK", "connections": [
    {"address": "192.0.2.1:17766", "incoming": False, "state": "synchronizing", "height": 5}]}}
conn_pre = {"result": {"status": "OK", "connections": [
    {"address": "192.0.2.1:17766", "incoming": False, "state": "before_handshake"}]}}
conn_in = {"result": {"status": "OK", "connections": [
    {"address": "192.0.2.1:17766", "incoming": True, "state": "normal"}]}}
record("handshake: outgoing synchronizing counts", bool(zc.handshaken_outgoing(conn_ok)), "")
record("handshake: before_handshake does not count", not zc.handshaken_outgoing(conn_pre), "")
record("handshake: incoming does not count", not zc.handshaken_outgoing(conn_in), "")
record("handshake: malformed answer", zc.handshaken_outgoing({"error": {}}) is None, "")


# 2. later samples: classification and Run.discovery on fixed in-memory answers
def online(**over):
    return good(**dict({"offline": False, "outgoing_connections_count": 1}, **over))


samples = [
    ("valid later sample", online(height=101), "valid"),
    ("BUSY with a height", online(status="BUSY", height=501), "busy"),
    ("RPC error beside a valid-looking result", dict(online(height=501), error={"code": -9, "message": "Core is busy"}), "rpc-error"),
    ("status FAILED", online(status="FAILED", height=2), "invalid"),
    ("later testnet", online(nettype="testnet", mainnet=False, height=2), "invalid"),
    ("later wrong version", online(version="2.3.0-0123abcde", height=2), "invalid"),
    ("later offline", online(offline=True, height=2), "invalid"),
    ("later result not an object", {"result": "OK"}, "invalid"),
    ("later height missing", {"result": {k: v for k, v in online()["result"].items() if k != "height"}}, "invalid"),
]
for name, info, want in samples:
    kind, detail = zc.classify_sample(info, "2.3.0-release")
    record(f"sample: {name}", kind == want, f"{kind}: {detail}")

HS = {"result": {"status": "OK", "connections": [
    {"address": "192.0.2.1:17766", "incoming": False, "state": "synchronizing", "height": 903440}]}}
NO_HS = {"result": {"status": "OK", "connections": []}}
REVIEW_FIXTURE = {"result": {"status": "FAILED", "offline": True, "version": "2.3.0-0123abcde",
                             "nettype": "testnet", "mainnet": False, "height": 2}}


class FakeProc:
    pid, returncode = 0, None

    def poll(self):
        return None


def discovery_in_memory(name, infos, conns, want_pass, expect=None):
    """Run.discovery with zc.rpc replaced; each list repeats its last answer."""
    seq = {"get_info": list(infos), "get_connections": list(conns)}
    calls = {"get_info": 0, "get_connections": 0}

    def fake_rpc(port, method, timeout, params=None):
        lst = seq[method]
        item = lst[min(calls[method], len(lst) - 1)]
        calls[method] += 1
        if isinstance(item, Exception):
            raise item
        return item

    args = types.SimpleNamespace(mode="discovery", ports=[1, 2, 3], request_timeout=1.0, poll=0.01,
                                 stop_on_pass=True, expect_version="2.3.0-release")
    run_obj = zc.Run(args)
    run_obj.proc, run_obj.polls, run_obj.t0 = FakeProc(), io.StringIO(), time.monotonic()
    saved_rpc, saved_err = zc.rpc, sys.stderr
    zc.rpc, sys.stderr = fake_rpc, io.StringIO()
    try:
        run_obj.discovery(time.monotonic() + 1.0, {"height": 1})
    finally:
        zc.rpc, sys.stderr = saved_rpc, saved_err
    c = run_obj.result["checks"]
    passed = c["outgoing_handshake"] and c["height_increased"] and not c["invalid_sample"]
    ok = passed == want_pass and all(c.get(k) == v for k, v in (expect or {}).items())
    record(f"discovery: {name}", ok, {k: c[k] for k in ("outgoing_handshake", "height_max", "invalid_sample", "samples")})


discovery_in_memory("valid progress passes", [online(height=1), online(height=101)], [HS], True,
                    {"height_max": 101})
discovery_in_memory("review fixture (FAILED/testnet/wrong version/offline, height 2) fails",
                    [online(height=1), REVIEW_FIXTURE], [HS], False, {"invalid_sample": True})
discovery_in_memory("valid first, later testnet fails", [online(height=1), online(height=201, nettype="testnet", mainnet=False)],
                    [HS], False, {"invalid_sample": True})
discovery_in_memory("valid first, later wrong version fails", [online(height=1), online(height=201, version="2.3.0-0123abcde")],
                    [HS], False, {"invalid_sample": True})
discovery_in_memory("valid first, later offline fails", [online(height=1), online(height=201, offline=True)],
                    [HS], False, {"invalid_sample": True})
discovery_in_memory("BUSY height not counted", [online(height=1), online(height=501, status="BUSY")], [HS], False,
                    {"invalid_sample": False, "height_max": 1, "outgoing_handshake": True})
discovery_in_memory("RPC error height not counted",
                    [online(height=1), dict(online(height=501), error={"code": -9, "message": "busy", "height": 501})],
                    [HS], False, {"invalid_sample": False, "height_max": 1, "outgoing_handshake": True})
discovery_in_memory("request errors not counted", [online(height=1), urllib.error.URLError("refused")], [HS], False,
                    {"invalid_sample": False, "height_max": 1})
discovery_in_memory("BUSY then valid progress passes", [online(height=1), online(status="BUSY", height=501), online(height=101)],
                    [HS], True, {"height_max": 101})
discovery_in_memory("height without handshake fails", [online(height=1), online(height=101)], [NO_HS], False,
                    {"outgoing_handshake": False})


# 3. scenario runs
def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    st = open(f"/proc/{pid}/stat").read().split()[2] if os.path.exists(f"/proc/{pid}/stat") else "?"
    return st != "Z"


def listening(ports):
    out = []
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                out.append(port)
        except OSError:
            pass
    return out


def run(name, mode, scenario, want_exit, max_s, binary=stub, extra=(), log=None, want_checks=None, want_problem=None,
        held_ports=()):
    log = log or os.path.join(work, name.replace(" ", "-"))
    data = log + "-data"
    env = dict(os.environ, STUB_SCENARIO=scenario)
    cmd = [sys.executable, "-I", check_py, mode, "--zephyrd", binary, "--data-dir", data,
           "--log-dir", log, "--expect-version", "2.3.0-release", "--ports", PORTS,
           "--ready-timeout", "8", "--stop-timeout", "3", "--request-timeout", "1", *extra]
    t = time.monotonic()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    el = time.monotonic() - t
    child_left = None
    result = {}
    rj = os.path.join(log, "result.json")
    if os.path.exists(rj):
        result = json.load(open(rj))
        pid = result.get("pid")
        child_left = alive(pid) if pid else None
    ports_open = [x for x in listening(int(x) for x in PORTS.split(",")) if x not in held_ports]
    checks = result.get("checks", {})
    bad_checks = {k: checks.get(k) for k, v in (want_checks or {}).items()
                  if not (v(checks.get(k)) if callable(v) else checks.get(k) == v)}
    problem_ok = want_problem is None or any(want_problem in t for t in result.get("problems", []))
    ok = (p.returncode == want_exit and el <= max_s and not child_left and not ports_open
          and not bad_checks and problem_ok)
    detail = f"exit {p.returncode} (want {want_exit}), {el:.1f}s (max {max_s}), child left {child_left}, listeners {ports_open}"
    if want_checks or want_problem:
        detail += f", checks {'ok' if not bad_checks else bad_checks}, problem {'ok' if problem_ok else 'missing ' + repr(want_problem)}"
    record(f"run: {name}", ok, detail)
    return p


run("good stub offline passes", "offline", "good", 0, 20)
run("early-exit stub fails", "offline", "early-exit", 1, 15)
run("TERM-ignoring stub fails and is killed", "offline", "ignore-term", 3, 25)
run("non-zero exit fails", "offline", "bad-exit", 1, 20)
run("wrong version fails", "offline", "wrong-version", 1, 20)
run("testnet fails", "offline", "testnet", 1, 20)
run("malformed RPC body fails", "offline", "malformed", 1, 20)
run("RPC error object fails", "offline", "rpc-error", 1, 20)
run("discovery without peers fails", "discovery", "good", 1, 30,
    extra=("--limit", "6", "--poll", "1"))

DISC = ("--limit", "12", "--poll", "0.5", "--stop-on-pass")
run("stub discovery with handshake and height increase passes", "discovery", "discover", 0, 20, extra=DISC,
    want_checks={"outgoing_handshake": True, "invalid_sample": False, "height_increased": True,
                 "height_max": lambda h: isinstance(h, int) and h >= 101})
run("stub discovery through a BUSY phase passes", "discovery", "busy-then-sync", 0, 25, extra=DISC,
    want_checks={"outgoing_handshake": True, "invalid_sample": False,
                 "samples": lambda s: isinstance(s, dict) and s.get("busy", 0) >= 1})
for scen, field in (("later-testnet", "nettype"), ("later-wrong-version", "version"),
                    ("later-offline", "offline"), ("later-failed", "status")):
    run(f"stub valid first, {scen} fails", "discovery", scen, 1, 20, extra=DISC,
        want_checks={"invalid_sample": True}, want_problem=field)
for scen, kind in (("later-busy-height", "busy"), ("later-rpc-error-height", "rpc-error"),
                   ("later-http-error-height", "request-error")):
    run(f"stub {scen} not counted", "discovery", scen, 1, 25, extra=("--limit", "6", "--poll", "0.5", "--stop-on-pass"),
        want_checks={"invalid_sample": False, "outgoing_handshake": True, "height_max": 1,
                     "samples": lambda s, kind=kind: isinstance(s, dict) and s.get(kind, 0) >= 1})

p = run("missing binary refused", "offline", "good", 2, 5, binary=os.path.join(work, "no-such-zephyrd"))
record("missing binary: nothing created", not os.path.exists(os.path.join(work, "missing-binary-refused")), "")

holder = subprocess.Popen([sys.executable, "-I", "-c",
                           "import socket,time\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',28391));s.listen();time.sleep(60)"])
time.sleep(0.5)
run("occupied port refused", "offline", "good", 2, 5, held_ports=(28391,))
record("occupied port: holder still running", holder.poll() is None, f"pid {holder.pid}")
holder.terminate()
holder.wait(timeout=10)

os.makedirs(os.path.join(work, "pre-existing"))
run("existing log dir refused", "offline", "good", 2, 5, log=os.path.join(work, "pre-existing"))

with open(os.path.join(work, "selftest-result.json"), "w") as f:
    json.dump({"failures": failures, "cases": results}, f, indent=2)
print(f"{len(results) - len(failures)}/{len(results)} cases as expected")
sys.exit(1 if failures else 0)
