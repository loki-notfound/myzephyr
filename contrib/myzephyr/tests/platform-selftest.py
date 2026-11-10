#!/usr/bin/env python3
"""Self-test of zephyrd-check.py's platform mechanics on the machine it runs on.

  platform-selftest.py <work-dir>     (<work-dir> must not exist)

Runs on Linux, macOS and Windows. Starts the stub daemon (stub-zephyrd.py, started with
this Python, never a real zephyrd) through zephyrd-check's own popen_kwargs() and stops it
with its own request_stop(): SIGTERM on POSIX, CTRL_BREAK_EVENT on Windows. Checks:
  - the stop request ends a cooperating child with exit 0 and closes its listener;
  - a child that ignores the request is still running after the timeout (zephyrd-check
    then kills it and reports a failed cleanup);
  - a child that exits non-zero after the request is seen as non-zero;
  - port_listening() sees the open listener and its absence afterwards;
  - the checker's own signal list matches the platform (no SIGHUP on Windows).
Exit 0 when every check gives the intended result.
"""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

here = os.path.dirname(os.path.abspath(__file__))
# no __pycache__ in the checkout: verify-source.sh counts ignored files as unclean
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("zephyrd_check", os.path.join(os.path.dirname(here), "zephyrd-check.py"))
zc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zc)
stub = os.path.join(here, "stub-zephyrd.py")
work = os.path.abspath(sys.argv[1]) if len(sys.argv) == 2 else sys.exit("usage: platform-selftest.py <work-dir>")
if os.path.lexists(work):
    sys.exit(f"{work} exists")
os.makedirs(work)
results = []


def record(name, ok, detail=""):
    results.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" -- {detail}" if detail and not ok else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start(scenario):
    port = free_port()
    env = dict(os.environ, STUB_SCENARIO=scenario)
    log = open(os.path.join(work, f"{scenario}.console"), "wb")
    p = subprocess.Popen([sys.executable, "-I", stub, "--rpc-bind-port", str(port), "--offline"],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, **zc.popen_kwargs())
    log.close()
    end = time.monotonic() + 20
    while time.monotonic() < end:
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": "0", "method": "get_info"}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/json_rpc", data=body, method="POST")
            with urllib.request.urlopen(req, timeout=1) as r:
                json.loads(r.read())
            return p, port
        except OSError:
            if p.poll() is not None:
                break
            time.sleep(0.2)
    return p, None


plat = "windows" if zc.IS_WINDOWS else sys.platform
want_method = "CTRL_BREAK_EVENT" if zc.IS_WINDOWS else "SIGTERM"
record(f"platform {plat}: signal list", ("SIGHUP" not in zc.OWN_SIGNALS and "SIGBREAK" in zc.OWN_SIGNALS) if zc.IS_WINDOWS
       else ("SIGHUP" in zc.OWN_SIGNALS and "SIGBREAK" not in zc.OWN_SIGNALS), str(zc.OWN_SIGNALS))

p, port = start("good")
record("cooperating stub ready", port is not None, f"exit {p.poll()}")
if port:
    record("listener seen while running", zc.port_listening(port))
    method = zc.request_stop(p)
    record(f"stop method is {want_method}", method == want_method, method)
    try:
        rc = p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        rc = None
        p.kill()
        p.wait(timeout=10)
    record("cooperating stub exits 0 after the stop request", rc == 0, f"exit {rc}")
    time.sleep(0.5)
    record("no listener after exit", not zc.port_listening(port))

p, port = start("ignore-term")
if port:
    zc.request_stop(p)
    try:
        p.wait(timeout=3)
        still = False
    except subprocess.TimeoutExpired:
        still = True
    record("ignoring stub still running after the timeout (would be a failed cleanup)", still)
    p.kill()
    p.wait(timeout=10)
    record("ignoring stub gone after kill", p.poll() is not None)
else:
    record("ignoring stub ready", False)

p, port = start("bad-exit")
if port:
    zc.request_stop(p)
    try:
        rc = p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        rc = None
        p.kill()
        p.wait(timeout=10)
    record("non-zero exit after the stop request is seen as non-zero", rc not in (0, None), f"exit {rc}")
else:
    record("bad-exit stub ready", False)

with open(os.path.join(work, "results.json"), "w") as f:
    json.dump({"platform": plat, "cases": results}, f, indent=2)
bad = [r for r in results if not r["ok"]]
print(f"{len(results) - len(bad)}/{len(results)} cases as expected on {plat}")
sys.exit(1 if bad else 0)
