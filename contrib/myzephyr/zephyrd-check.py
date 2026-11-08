#!/usr/bin/env python3
"""Bounded start checks for a zephyrd binary.

Modes
  offline     start with --offline in a fresh data directory, require a strict
              get_info answer, stop with SIGTERM and require a clean exit.
  discovery   start without --offline and without any peer option; pass only if
              an outgoing peer completes the handshake and the locally processed
              height increases before the limit. Every later get_info sample is
              held to the same assertions as the first: an invalid one fails the
              run; BUSY answers, RPC error objects and failed requests are
              recorded as transient and never contribute a height or handshake.
  manual-peer as discovery, but with one --add-exclusive-node, --out-peers 1 and
              --in-peers 0. A diagnostic of that peer, never a default-bootstrap result.
  expected-version
              print the version string a build of a source checkout reports:
              "<number>-release" when a tag points at HEAD, else "<number>-<sha9>"
              (cmake/GitVersion.cmake).

Every launch uses loopback listeners, --no-igd, --non-interactive, an empty explicit
config file, and new data and log directories (existing ones are refused). Only the
child started here is ever signalled; there is no kill by name. All waits are bounded
by monotonic deadlines. Exit status: 0 pass, 1 check failed, 2 usage or precondition
error (nothing started), 3 the child had to be killed or a listener stayed open.
Results: <log-dir>/result.json, polls in <log-dir>/polls.jsonl, daemon log and console.
"""
import argparse
import datetime
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_CLEANUP = 0, 1, 2, 3
HANDSHAKE_STATES = {"synchronizing", "standby", "normal", "idle"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+-(release|[0-9a-f]{9})$")
# failed requests: refused/reset connections, timeouts, HTTP errors, non-JSON bodies
REQUEST_ERRORS = (OSError, urllib.error.URLError, ValueError, http.client.HTTPException)
INFO_FIELDS = ("status", "offline", "height", "target_height", "outgoing_connections_count",
               "incoming_connections_count", "white_peerlist_size", "grey_peerlist_size",
               "synchronized", "version", "nettype", "mainnet")


class Interrupted(Exception):
    pass


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def usage_error(msg):
    print(f"zephyrd-check: {msg}", file=sys.stderr)
    sys.exit(EXIT_USAGE)


# ---------------------------------------------------------------- assertions
def check_info(info, expect_version, expect_offline, nettype="mainnet"):
    """Return a list of problems with a parsed get_info JSON-RPC answer."""
    errs = []
    if not isinstance(info, dict):
        return ["answer is not a JSON object"]
    if "error" in info:
        return [f"RPC error: {info['error']!r}"]
    res = info.get("result")
    if not isinstance(res, dict):
        return ["no result object"]
    if res.get("status") != "OK":
        errs.append(f"status {res.get('status')!r}, expected 'OK'")
    if res.get("offline") is not expect_offline:
        errs.append(f"offline {res.get('offline')!r}, expected {expect_offline}")
    ver = res.get("version")
    if not isinstance(ver, str) or not VERSION_RE.match(ver):
        errs.append(f"version {ver!r} has not the form <number>-release or <number>-<sha9>")
    elif ver != expect_version:
        errs.append(f"version {ver!r}, expected {expect_version!r}")
    if res.get("nettype") != nettype:
        errs.append(f"nettype {res.get('nettype')!r}, expected {nettype!r}")
    if nettype == "mainnet" and res.get("mainnet") is not True:
        errs.append(f"mainnet {res.get('mainnet')!r}, expected True")
    h = res.get("height")
    if not isinstance(h, int) or isinstance(h, bool) or h < 1:
        errs.append(f"height {h!r}, expected an integer >= 1")
    if expect_offline and res.get("outgoing_connections_count") != 0:
        errs.append(f"outgoing_connections_count {res.get('outgoing_connections_count')!r}, expected 0 offline")
    return errs


def classify_sample(info, expect_version, expect_offline=False):
    """Classify one get_info answer polled after readiness.

    Returns (kind, detail):
      ("valid", height)       passes every check_info assertion; only these may
                              contribute a height or a handshake observation;
      ("busy", text)          status BUSY: the daemon is temporarily unable to
                              answer; its fields, height included, are ignored;
      ("rpc-error", text)     a JSON-RPC error object; whatever else the answer
                              carries, height included, is ignored;
      ("invalid", problems)   any other answer: wrong network, version or offline
                              state, another status, a malformed answer. Fatal.
    A valid earlier answer never excuses a later invalid one.
    """
    if isinstance(info, dict) and "error" in info:
        return "rpc-error", f"RPC error: {info['error']!r}"
    res = info.get("result") if isinstance(info, dict) else None
    if isinstance(res, dict) and res.get("status") == "BUSY":
        return "busy", "status 'BUSY'"
    errs = check_info(info, expect_version, expect_offline)
    if errs:
        return "invalid", errs
    return "valid", res["height"]


def handshaken_outgoing(conns):
    """Outgoing connections that completed the P2P handshake."""
    res = conns.get("result") if isinstance(conns, dict) else None
    if not isinstance(res, dict) or res.get("status") != "OK":
        return None
    out = []
    for c in res.get("connections") or []:
        if isinstance(c, dict) and c.get("incoming") is False and c.get("state") in HANDSHAKE_STATES:
            out.append({k: c.get(k) for k in ("address", "state", "height", "peer_id", "live_time")})
    return out


# ---------------------------------------------------------------- rpc
def rpc(port, method, timeout, params=None):
    body = {"jsonrpc": "2.0", "id": "0", "method": method}
    if params is not None:
        body["params"] = params
    return post(port, "/json_rpc", body, timeout)


def post(port, path, body, timeout):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(4 * 1024 * 1024)
    return json.loads(raw)


# ---------------------------------------------------------------- ports
def port_free(port):
    """Bind test with SO_REUSEADDR, as zephyrd's acceptors bind: TIME_WAIT left by
    earlier connections does not count as busy, a listening socket does."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------- run
class Run:
    def __init__(self, args):
        self.a = args
        self.proc = None
        self.result = {"mode": args.mode, "started": None, "checks": {}, "problems": []}
        self.polls = None

    def problem(self, text):
        self.result["problems"].append(text)
        print(f"zephyrd-check: {text}", file=sys.stderr)

    def remaining(self, deadline):
        return deadline - time.monotonic()

    def command(self):
        a = self.a
        cmd = [a.zephyrd, "--data-dir", a.data_dir, "--config-file", self.conf,
               "--no-igd", "--non-interactive",
               "--p2p-bind-ip", "127.0.0.1", "--p2p-bind-port", str(a.ports[0]),
               "--rpc-bind-ip", "127.0.0.1", "--rpc-bind-port", str(a.ports[1]),
               "--zmq-rpc-bind-ip", "127.0.0.1", "--zmq-rpc-bind-port", str(a.ports[2]),
               "--log-level", "1", "--log-file", os.path.join(a.log_dir, "zephyrd.log")]
        if a.mode == "offline":
            cmd.append("--offline")
        if a.mode == "manual-peer":
            cmd += ["--add-exclusive-node", a.exclusive_node, "--out-peers", "1", "--in-peers", "0"]
        return cmd

    def start(self):
        a = self.a
        os.makedirs(a.log_dir)
        os.makedirs(a.data_dir)
        self.conf = os.path.join(a.log_dir, "empty.conf")
        open(self.conf, "w").close()
        self.polls = open(os.path.join(a.log_dir, "polls.jsonl"), "w")
        cmd = self.command()
        self.result["command"] = cmd
        console = open(os.path.join(a.log_dir, "console.txt"), "wb")
        self.result["started"] = utc()
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=console,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        console.close()
        self.result["pid"] = self.proc.pid
        print(f"zephyrd-check: started pid {self.proc.pid} at {self.result['started']}")

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def log_poll(self, rec):
        rec = dict(rec, t=utc(), elapsed=round(time.monotonic() - self.t0, 1))
        self.polls.write(json.dumps(rec, sort_keys=True) + "\n")
        self.polls.flush()

    def wait_ready(self, deadline, expect_offline):
        """Poll get_info until it parses and passes, the child dies, or the deadline."""
        last = None
        while True:
            if not self.alive():
                self.problem(f"daemon exited early with code {self.proc.returncode}")
                return None
            left = self.remaining(deadline)
            if left <= 0:
                self.problem(f"no valid get_info before the deadline; last: {last}")
                return None
            try:
                info = rpc(self.a.ports[1], "get_info", min(self.a.request_timeout, max(left, 0.1)))
            except REQUEST_ERRORS as e:
                last = f"{type(e).__name__}: {e}"
                self.log_poll({"get_info": None, "error": last})
                time.sleep(min(1.0, max(left, 0)))
                continue
            errs = check_info(info, self.a.expect_version, expect_offline)
            res = info.get("result") if isinstance(info, dict) else None
            self.log_poll({"get_info": res if res is not None else info, "problems": errs})
            if not errs:
                return res
            status = res.get("status") if isinstance(res, dict) else None
            if isinstance(status, str) and status != "OK" and "error" not in info:
                last = errs  # a well-formed answer that is not ready yet (e.g. BUSY); keep polling
                time.sleep(min(1.0, max(self.remaining(deadline), 0)))
                continue
            for e in errs:
                self.problem(f"get_info: {e}")
            return None

    def discovery(self, deadline, first):
        """Poll until handshake + height increase (or the deadline).

        Every poll asks get_info first and classifies the answer (classify_sample).
        Only a valid sample counts: its height may raise the maximum, and only
        after it is get_connections asked for a handshake observation. BUSY
        answers, JSON-RPC error objects and failed requests (timeouts, refused
        connections, HTTP errors, bodies that are not JSON) are counted and logged
        as transient; nothing they carry, height included, is used. An invalid
        sample (wrong network, version or offline state, another status, a
        malformed answer) fails the run at once, however valid earlier ones were.
        """
        h0 = first["height"]
        counts = {"valid": 0, "invalid": 0, "busy": 0, "rpc-error": 0, "request-error": 0,
                  "connections-error": 0}
        seen_handshake, max_height, invalid = [], h0, None
        while True:
            if not self.alive():
                self.problem(f"daemon exited early with code {self.proc.returncode}")
                break
            left = self.remaining(deadline)
            if left <= 0:
                break
            rec = {}
            info = None
            try:
                info = rpc(self.a.ports[1], "get_info", min(self.a.request_timeout, left))
            except REQUEST_ERRORS as e:
                kind, detail = "request-error", f"{type(e).__name__}: {e}"
            else:
                kind, detail = classify_sample(info, self.a.expect_version, False)
            counts[kind] += 1
            rec["sample"] = kind
            res = info.get("result") if isinstance(info, dict) else None
            if isinstance(res, dict):
                rec["get_info"] = {k: res.get(k) for k in INFO_FIELDS}
            elif info is not None:
                rec["get_info_raw"] = repr(info)[:500]
            if kind == "valid":
                max_height = max(max_height, detail)
                try:
                    conns = rpc(self.a.ports[1], "get_connections",
                                min(self.a.request_timeout, max(self.remaining(deadline), 0.1)))
                except REQUEST_ERRORS as e:
                    counts["connections-error"] += 1
                    rec["connections_error"] = f"{type(e).__name__}: {e}"
                else:
                    hs = handshaken_outgoing(conns)
                    if hs is None:
                        counts["connections-error"] += 1
                        rec["connections_error"] = f"not a valid get_connections answer: {repr(conns)[:300]}"
                    else:
                        rec["handshaken_outgoing"] = hs
                        if hs:
                            seen_handshake = hs
            else:
                rec["detail"] = detail
            self.log_poll(rec)
            if kind == "invalid":
                invalid = detail
                break
            passed = bool(seen_handshake) and max_height > h0
            if passed and self.a.stop_on_pass:
                break
            time.sleep(max(0.0, min(self.a.poll, self.remaining(deadline))))
        c = self.result["checks"]
        c["outgoing_handshake"] = bool(seen_handshake)
        c["height_start"] = h0
        c["height_max"] = max_height
        c["height_increased"] = max_height > h0
        c["invalid_sample"] = invalid is not None
        c["samples"] = counts
        self.result["handshaken_peers"] = seen_handshake
        if invalid is not None:
            for e in invalid:
                self.problem(f"get_info after readiness: {e}")
        if not seen_handshake:
            self.problem("no outgoing peer completed the handshake")
        if max_height <= h0:
            self.problem(f"locally processed height in valid samples did not increase (stayed {h0})")

    def snapshot_extra(self):
        """Peer list and block hashes, best effort, before shutdown."""
        if not self.alive():
            return
        t = self.a.request_timeout
        try:
            pl = post(self.a.ports[1], "/get_peer_list", {}, t)
            self.result["peer_list"] = {"white": len(pl.get("white_list") or []),
                                        "gray": len(pl.get("gray_list") or [])}
        except (OSError, urllib.error.URLError, ValueError, AttributeError) as e:
            self.result["peer_list"] = f"{type(e).__name__}: {e}"
        hashes = {}
        for h in self.a.hash_heights:
            try:
                r = rpc(self.a.ports[1], "get_block_header_by_height", t, {"height": h})
                hashes[str(h)] = r.get("result", {}).get("block_header", {}).get("hash")
            except (OSError, urllib.error.URLError, ValueError, AttributeError) as e:
                hashes[str(h)] = f"{type(e).__name__}: {e}"
        if hashes:
            self.result["block_hashes"] = hashes
        try:
            r = rpc(self.a.ports[1], "get_info", t)
            self.result["final_get_info"] = r.get("result")
        except (OSError, urllib.error.URLError, ValueError, AttributeError) as e:
            self.result["final_get_info"] = f"{type(e).__name__}: {e}"

    def stop(self):
        """SIGTERM to our child, bounded wait, bounded kill, listener check. Returns ok."""
        ok = True
        if self.proc is None:
            return True
        if self.proc.poll() is None:
            self.result["sigterm_at"] = utc()
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=self.a.stop_timeout)
            except subprocess.TimeoutExpired:
                ok = False
                self.problem(f"pid {self.proc.pid} did not exit within {self.a.stop_timeout}s of SIGTERM; killing it")
                self.proc.kill()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.problem(f"pid {self.proc.pid} still present 10s after SIGKILL")
        self.result["exit_code"] = self.proc.returncode
        self.result["exited_at"] = utc()
        if self.proc.returncode not in (0, None) and ok:
            self.problem(f"daemon exit code {self.proc.returncode}")
        open_ports = []
        end = time.monotonic() + 5
        while True:
            open_ports = [p for p in self.a.ports if port_listening(p)]
            if not open_ports or time.monotonic() > end:
                break
            time.sleep(0.5)
        self.result["listeners_after"] = open_ports
        if open_ports:
            ok = False
            self.problem(f"listeners still open after exit: {open_ports}")
        return ok


def run_daemon_mode(a):
    for p in (a.data_dir, a.log_dir):
        if os.path.lexists(p):
            usage_error(f"{p} exists; refusing to reuse or overwrite a measurement")
        if not os.path.isdir(os.path.dirname(os.path.abspath(p))):
            usage_error(f"parent of {p} does not exist")
    if not (os.path.isfile(a.zephyrd) and os.access(a.zephyrd, os.X_OK)):
        usage_error(f"{a.zephyrd} is not an executable file")
    if len(set(a.ports)) != 3 or any(not 1024 <= p <= 65535 for p in a.ports):
        usage_error("--ports needs three distinct ports between 1024 and 65535")
    busy = [p for p in a.ports if not port_free(p)]
    if busy:
        usage_error(f"port(s) {busy} on 127.0.0.1 already in use; nothing started")
    if not VERSION_RE.match(a.expect_version):
        usage_error(f"--expect-version {a.expect_version!r} is not <number>-release or <number>-<sha9>")
    if a.mode == "manual-peer" and not re.match(r"^[A-Za-z0-9.-]+:\d{1,5}$", a.exclusive_node or ""):
        usage_error("manual-peer needs --exclusive-node host:port")

    run = Run(a)
    run.result["zephyrd"] = os.path.abspath(a.zephyrd)
    run.result["expect_version"] = a.expect_version

    def on_signal(signum, _frame):
        raise Interrupted(signal.Signals(signum).name)

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, on_signal)

    verdict_ok = False
    cleanup_ok = True
    try:
        run.start()
        expect_offline = a.mode == "offline"
        limit = a.ready_timeout if a.mode == "offline" else a.limit
        deadline = run.t0 + limit
        first = run.wait_ready(min(deadline, run.t0 + a.ready_timeout), expect_offline)
        run.result["checks"]["ready"] = first is not None
        if first is not None:
            run.result["first_get_info"] = first
            if a.mode == "offline":
                verdict_ok = True
            else:
                run.discovery(deadline, first)
                c = run.result["checks"]
                verdict_ok = (c["outgoing_handshake"] and c["height_increased"]
                              and not c["invalid_sample"])
        run.snapshot_extra()
    except Interrupted as e:
        run.problem(f"interrupted by {e}")
        verdict_ok = False
    finally:
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, signal.SIG_IGN)
        cleanup_ok = run.stop()
        if run.polls:
            run.polls.close()
        exit_ok = run.result.get("exit_code") == 0
        run.result["checks"]["clean_shutdown"] = cleanup_ok and exit_ok
        status = EXIT_PASS if (verdict_ok and cleanup_ok and exit_ok) else (EXIT_CLEANUP if not cleanup_ok else EXIT_FAIL)
        run.result["verdict"] = {EXIT_PASS: "passed", EXIT_FAIL: "failed", EXIT_CLEANUP: "failed-cleanup"}[status]
        run.result["finished"] = utc()
        with open(os.path.join(a.log_dir, "result.json"), "w") as f:
            json.dump(run.result, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"zephyrd-check: {a.mode} {run.result['verdict']} (exit {status})")
    sys.exit(status)


def expected_version(checkout):
    src = open(os.path.join(checkout, "src", "version.cpp.in")).read()
    m = re.search(r'#define DEF_MONERO_VERSION "([0-9.]+)"', src)
    if not m:
        usage_error("DEF_MONERO_VERSION not found")
    tags = subprocess.run(["git", "-C", checkout, "tag", "-l", "--points-at", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.split()
    if tags:
        return f"{m.group(1)}-release"
    sha = subprocess.run(["git", "-C", checkout, "rev-parse", "--short=9", "HEAD"],
                         check=True, capture_output=True, text=True).stdout.strip()
    return f"{m.group(1)}-{sha[:9]}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["offline", "discovery", "manual-peer", "expected-version"])
    p.add_argument("--zephyrd")
    p.add_argument("--data-dir")
    p.add_argument("--log-dir")
    p.add_argument("--expect-version")
    p.add_argument("--checkout", help="for expected-version")
    p.add_argument("--ports", default="28380,28381,28382", help="p2p,rpc,zmq on 127.0.0.1")
    p.add_argument("--ready-timeout", type=float, default=60.0)
    p.add_argument("--limit", type=float, default=600.0, help="discovery/manual-peer run limit, s")
    p.add_argument("--poll", type=float, default=15.0)
    p.add_argument("--request-timeout", type=float, default=5.0)
    p.add_argument("--stop-timeout", type=float, default=60.0)
    p.add_argument("--stop-on-pass", action="store_true")
    p.add_argument("--exclusive-node")
    p.add_argument("--hash-heights", default="", help="comma list, recorded before shutdown")
    a = p.parse_args()
    if a.mode == "expected-version":
        if not a.checkout:
            usage_error("expected-version needs --checkout")
        print(expected_version(a.checkout))
        return
    for name in ("zephyrd", "data_dir", "log_dir", "expect_version"):
        if not getattr(a, name):
            usage_error(f"--{name.replace('_', '-')} is required")
    try:
        a.ports = [int(x) for x in a.ports.split(",")]
        a.hash_heights = [int(x) for x in a.hash_heights.split(",") if x]
    except ValueError:
        usage_error("--ports and --hash-heights take comma-separated integers")
    if len(a.ports) != 3:
        usage_error("--ports needs exactly three values")
    for name in ("ready_timeout", "limit", "poll", "request_timeout", "stop_timeout"):
        v = getattr(a, name)
        if not 0 < v <= 3600:
            usage_error(f"--{name.replace('_', '-')} must be in (0, 3600]")
    if a.mode != "manual-peer" and a.exclusive_node:
        usage_error("--exclusive-node is only allowed in manual-peer mode")
    run_daemon_mode(a)


if __name__ == "__main__":
    main()
