#!/usr/bin/env python3
"""Self-test of zephyrd-check.py's platform mechanics on the machine it runs on.

  platform-selftest.py [--stub FILE] [--ready-window SECONDS] <work-dir>
                                      (<work-dir> must not exist)

--stub and --ready-window exist for the harness self-test, which runs this self-test
against a stub that never listens and requires a failure with diagnostics.

Runs on Linux, macOS and Windows. Starts the stub daemon (stub-zephyrd.py, started with
this Python, never a real zephyrd) through zephyrd-check's own popen_kwargs(), polls it
with zephyrd-check's own rpc() and stops it with its own request_stop(): SIGTERM on
POSIX, CTRL_BREAK_EVENT on Windows. Checks:
  - the stop request ends a cooperating child with exit 0 and closes its listener;
  - a child that ignores the request is still running after the timeout (zephyrd-check
    then kills it and reports a failed cleanup);
  - a child that exits non-zero after the request is seen as non-zero;
  - port_listening() sees the open listener and its absence afterwards;
  - the checker's own signal list matches the platform (no SIGHUP on Windows);
  - a child that never listens is reported as not ready, with the diagnostics below,
    and is stopped afterwards (expected negative case).

Diagnostics: before the cases, the platform facts (Python version and executable, the
proxies urllib would take from the environment and system settings, and the time a
reverse lookup of 127.0.0.1 takes, capped) go to stdout and platform-facts.json. On
every "not ready" or unexpected result the self-test prints the stub's console file,
the elapsed time, the child's state, whether the port accepts TCP, the last request
error and the Python version, and writes them to <case>.diagnostics.json; results.json
carries them too. A stub left running after a failed case is killed (no orphans).
Exit 0 when every check gives the intended result.
"""
import argparse
import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import urllib.request

here = os.path.dirname(os.path.abspath(__file__))
# no __pycache__ in the checkout: verify-source.sh counts ignored files as unclean
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("zephyrd_check", os.path.join(os.path.dirname(here), "zephyrd-check.py"))
zc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zc)
stub = os.path.join(here, "stub-zephyrd.py")
READY_WINDOW = 20.0
NEVER_READY_WINDOW = 3.0
LOOKUP_CAP = 25.0
results = []
work = None


def py_version():
    return f"{platform.python_implementation()} {platform.python_version()}"


def record(name, ok, detail="", diag=None):
    entry = {"case": name, "ok": bool(ok), "detail": detail}
    if diag is not None:
        entry["diagnostics"] = diag
    results.append(entry)
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" -- {detail}" if detail and not ok else ""))
    if not ok and diag is not None:
        show(name, diag)


def show(name, diag):
    """Print diagnostics in the job log and keep them in the work directory."""
    print(f"---- diagnostics: {name}")
    for k in ("scenario", "python", "elapsed_s", "child", "port", "port_accepts_tcp", "last_request_error"):
        print(f"  {k}: {diag.get(k)}")
    print(f"  console ({diag.get('console_file')}):")
    for line in (diag.get("console") or "(empty)").splitlines():
        print(f"    | {line}")
    print("---- end of diagnostics")
    slug = "".join(c if c.isalnum() else "-" for c in name).strip("-")
    with open(os.path.join(work, f"{slug}.diagnostics.json"), "w") as f:
        json.dump(dict(diag, case=name), f, indent=2)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Child:
    """One stub child: process, port, console file, start time, last request error."""

    def __init__(self, scenario, window, stub):
        self.scenario = scenario
        self.port = free_port()
        self.console = os.path.join(work, f"{scenario}.console")
        env = dict(os.environ, STUB_SCENARIO=scenario)
        log = open(self.console, "wb")
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen([sys.executable, "-I", stub, "--rpc-bind-port", str(self.port), "--offline"],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                     **zc.popen_kwargs())
        log.close()
        self.last_error = None
        self.ready_after = None
        self.ready = self.wait_ready(window)

    def wait_ready(self, window):
        end = self.t0 + window
        while time.monotonic() < end:
            try:
                zc.rpc(self.port, "get_info", 1)
                self.ready_after = round(time.monotonic() - self.t0, 3)
                return True
            except zc.REQUEST_ERRORS as e:
                self.last_error = f"{type(e).__name__}: {e}"
                if self.proc.poll() is not None:
                    break
                time.sleep(0.2)
        return False

    def diagnostics(self):
        rc = self.proc.poll()
        try:
            with open(self.console, "rb") as f:
                console = f.read(64 * 1024).decode("utf-8", "replace")
        except OSError as e:
            console = f"(cannot read: {e})"
        return {"scenario": self.scenario, "python": py_version(), "executable": sys.executable,
                "elapsed_s": round(time.monotonic() - self.t0, 3),
                "child": "running" if rc is None else f"exited {rc}", "port": self.port,
                "port_accepts_tcp": zc.port_listening(self.port), "last_request_error": self.last_error,
                "console_file": os.path.basename(self.console), "console": console}

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def platform_facts():
    """Facts that decide whether loopback requests can work, measured before the cases."""
    facts = {"python": py_version(), "executable": sys.executable, "sys_platform": sys.platform,
             "platform": platform.platform()}
    try:
        facts["proxies_urllib_would_use"] = sorted(urllib.request.getproxies())  # names only, never values
        facts["urllib_bypasses_proxy_for_127.0.0.1"] = bool(urllib.request.proxy_bypass("127.0.0.1"))
    except Exception as e:  # a diagnostic must not end the self-test
        facts["proxies_urllib_would_use"] = f"{type(e).__name__}: {e}"
    box = {}

    def lookup():
        t = time.monotonic()
        try:
            box["result"] = socket.getfqdn("127.0.0.1")
        except Exception as e:
            box["result"] = f"{type(e).__name__}: {e}"
        box["seconds"] = round(time.monotonic() - t, 3)

    th = threading.Thread(target=lookup, daemon=True)
    th.start()
    th.join(LOOKUP_CAP)
    facts["getfqdn_127.0.0.1"] = box.get("result", f"still running after {LOOKUP_CAP:.0f} s")
    facts["getfqdn_127.0.0.1_seconds"] = box.get("seconds")
    return facts


def main():
    global work
    ap = argparse.ArgumentParser(description="platform self-test of zephyrd-check's start mechanics")
    ap.add_argument("--stub", default=stub, help="stand-in daemon (default: stub-zephyrd.py)")
    ap.add_argument("--ready-window", type=float, default=READY_WINDOW, help="seconds a stub has to answer")
    ap.add_argument("work")
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    if os.path.lexists(work):
        sys.exit(f"{work} exists")
    os.makedirs(work)

    facts = platform_facts()
    print("platform facts: " + json.dumps(facts, sort_keys=True))
    with open(os.path.join(work, "platform-facts.json"), "w") as f:
        json.dump(facts, f, indent=2, sort_keys=True)

    plat = "windows" if zc.IS_WINDOWS else sys.platform
    want_method = "CTRL_BREAK_EVENT" if zc.IS_WINDOWS else "SIGTERM"
    record(f"platform {plat}: signal list", ("SIGHUP" not in zc.OWN_SIGNALS and "SIGBREAK" in zc.OWN_SIGNALS) if zc.IS_WINDOWS
           else ("SIGHUP" in zc.OWN_SIGNALS and "SIGBREAK" not in zc.OWN_SIGNALS), str(zc.OWN_SIGNALS))

    c = Child("good", a.ready_window, a.stub)
    record("cooperating stub ready", c.ready, f"exit {c.proc.poll()}", None if c.ready else c.diagnostics())
    if c.ready:
        print(f"     ready after {c.ready_after} s")
        seen = zc.port_listening(c.port)
        record("listener seen while running", seen, "", None if seen else c.diagnostics())
        method = zc.request_stop(c.proc)
        record(f"stop method is {want_method}", method == want_method, method)
        try:
            rc = c.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            rc = None
        diag = None if rc == 0 else c.diagnostics()
        c.kill()
        record("cooperating stub exits 0 after the stop request", rc == 0, f"exit {rc}", diag)
        time.sleep(0.5)
        record("no listener after exit", not zc.port_listening(c.port))
    c.kill()

    c = Child("ignore-term", a.ready_window, a.stub)
    if c.ready:
        zc.request_stop(c.proc)
        try:
            c.proc.wait(timeout=3)
            still = False
        except subprocess.TimeoutExpired:
            still = True
        record("ignoring stub still running after the timeout (would be a failed cleanup)", still, "",
               None if still else c.diagnostics())
        c.kill()
        record("ignoring stub gone after kill", c.proc.poll() is not None)
    else:
        record("ignoring stub ready", False, "", c.diagnostics())
    c.kill()

    c = Child("bad-exit", a.ready_window, a.stub)
    if c.ready:
        zc.request_stop(c.proc)
        try:
            rc = c.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            rc = None
        ok = rc not in (0, None)
        record("non-zero exit after the stop request is seen as non-zero", ok, f"exit {rc}",
               None if ok else c.diagnostics())
    else:
        record("bad-exit stub ready", False, "", c.diagnostics())
    c.kill()

    # expected negative case: the diagnostics path itself
    c = Child("never-listen", NEVER_READY_WINDOW, a.stub)
    diag = c.diagnostics()
    print("     expected: the never-listening stub is not ready; its diagnostics follow")
    show("never-listening stub (expected not ready)", diag)
    complete = (diag["child"] == "running" and diag["port_accepts_tcp"] is False
                and diag["elapsed_s"] >= NEVER_READY_WINDOW and diag["python"] == py_version()
                and bool(diag["last_request_error"]) and "never listening" in diag["console"])
    record("never-listening stub reported not ready, with console, elapsed time, TCP state and Python version",
           not c.ready and complete, f"ready {c.ready}, diagnostics {diag}")
    c.kill()
    record("never-listening stub gone after kill", c.proc.poll() is not None)

    with open(os.path.join(work, "results.json"), "w") as f:
        json.dump({"platform": plat, "python": py_version(), "facts": facts, "cases": results}, f, indent=2)
    bad = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(bad)}/{len(results)} cases as expected on {plat}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
