#!/usr/bin/env python3
"""A stand-in for zephyrd used only by the harness self-test.

Accepts zephyrd-style arguments, reads --rpc-bind-port and --offline, and behaves
according to STUB_SCENARIO:
  good            serve a valid mainnet get_info, exit 0 on SIGTERM
  early-exit      exit 3 at once
  ignore-term     serve a valid get_info and ignore SIGTERM (must be killed)
  bad-exit        serve a valid get_info, exit 1 on SIGTERM
  wrong-version   serve version 2.3.0-0123abcde (well-formed, not the expected one)
  testnet         serve nettype testnet
  malformed       serve a body that is not JSON
  rpc-error       serve a JSON-RPC error object

Scenarios with phases (seconds since the stub started; the first phase is a valid,
ready mainnet answer at height 1):
  discover        until 1.5 s one outgoing connection before the handshake, then an
                  outgoing "synchronizing" peer and a height that grows by 100 per
                  second (1, 101, 201, ...): a successful discovery
  busy-then-sync  outgoing peer from the start; 3 s to 4.5 s status BUSY, then the
                  height grows by 100 per second
  later-testnet, later-wrong-version, later-offline, later-failed
                  outgoing peer from the start; after 3 s a higher height together
                  with nettype testnet / version 2.3.0-0123abcde / offline true /
                  status FAILED with testnet, offline and the wrong version at once
  later-busy-height, later-rpc-error-height, later-http-error-height
                  outgoing peer from the start; after 3 s a misleading height of
                  501 inside a BUSY answer / beside a JSON-RPC error object / in the
                  JSON body of an HTTP 500 answer
"""
import http.server
import json
import os
import signal
import sys
import time

scenario = os.environ.get("STUB_SCENARIO", "good")
args = sys.argv[1:]
port = int(args[args.index("--rpc-bind-port") + 1])
offline = "--offline" in args
t_start = time.monotonic()
SWITCH = 3.0  # leaves room for the harness to see one valid sample with the peer first
PEER_EARLY = ("busy-then-sync", "later-testnet", "later-wrong-version", "later-offline",
              "later-failed", "later-busy-height", "later-rpc-error-height", "later-http-error-height")


def phase_time():
    return time.monotonic() - t_start


def grown_height(since):
    return 1 + 100 * (int(phase_time() - since) + 1) if phase_time() >= since else 1

if scenario == "early-exit":
    sys.exit(3)


def info():
    res = {"status": "OK", "offline": offline, "version": "2.3.0-release", "nettype": "mainnet",
           "mainnet": True, "height": 1, "target_height": 0, "outgoing_connections_count": 0,
           "incoming_connections_count": 0, "untrusted": False, "restricted": False}
    if scenario == "wrong-version":
        res["version"] = "2.3.0-0123abcde"
    if scenario == "testnet":
        res["nettype"], res["mainnet"] = "testnet", False
    t = phase_time()
    if scenario in ("discover", "busy-then-sync") or scenario in PEER_EARLY:
        res["target_height"] = 903440
        res["outgoing_connections_count"] = 1 if (scenario in PEER_EARLY or t >= 1.5) else 0
    if scenario == "discover":
        res["height"] = grown_height(1.5)
    elif scenario == "busy-then-sync":
        if SWITCH <= t < SWITCH + 1.5:
            res["status"] = "BUSY"
        res["height"] = grown_height(SWITCH + 1.5)
    elif scenario.startswith("later-") and t >= SWITCH:
        res["height"] = 201
        if scenario == "later-testnet":
            res["nettype"], res["mainnet"] = "testnet", False
        elif scenario == "later-wrong-version":
            res["version"] = "2.3.0-0123abcde"
        elif scenario == "later-offline":
            res["offline"] = True
        elif scenario == "later-failed":
            res.update(status="FAILED", offline=True, version="2.3.0-0123abcde",
                       nettype="testnet", mainnet=False)
        elif scenario == "later-busy-height":
            res.update(status="BUSY", height=501)
        elif scenario == "later-rpc-error-height":
            res["height"] = 501
            return {"id": "0", "jsonrpc": "2.0", "result": res,
                    "error": {"code": -9, "message": "Core is busy", "height": 501}}
    return {"id": "0", "jsonrpc": "2.0", "result": res}


def connections():
    if scenario in PEER_EARLY or (scenario == "discover" and phase_time() >= 1.5):
        state = "synchronizing"
    elif scenario == "discover":
        state = "before_handshake"
    else:
        return []
    return [{"address": "192.0.2.10:17766", "incoming": False, "state": state,
             "height": 903440, "peer_id": "00000000000000aa", "live_time": int(phase_time())}]


class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        if scenario == "malformed":
            body = b"<html>not json"
        elif scenario == "rpc-error":
            body = json.dumps({"id": "0", "jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}}).encode()
        elif req.get("method") == "get_info":
            body = json.dumps(info()).encode()
        elif req.get("method") == "get_connections":
            body = json.dumps({"id": "0", "jsonrpc": "2.0", "result": {"status": "OK", "connections": connections()}}).encode()
        else:
            body = json.dumps({"id": "0", "jsonrpc": "2.0", "result": {"status": "OK"}}).encode()
        code = 200
        if scenario == "later-http-error-height" and req.get("method") == "get_info" and phase_time() >= SWITCH:
            code = 500
            body = json.dumps({"id": "0", "jsonrpc": "2.0", "result": dict(info()["result"], height=501)}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", port), H)


def on_term(signum, frame):
    srv.server_close()
    sys.exit(1 if scenario == "bad-exit" else 0)


signal.signal(signal.SIGTERM, signal.SIG_IGN if scenario == "ignore-term" else on_term)
srv.serve_forever()
