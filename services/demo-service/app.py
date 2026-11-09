#!/usr/bin/env python3
"""Synthetic iGaming-style demo service (stdlib only).

One image, five personalities selected by SERVICE_NAME: game-api, game-web, wallet-mock,
authentication-service, leaderboard-service. Everything is SYNTHETIC: fake players, a fake "DEMO"
currency, no connection to any gambling platform, payment provider or real money.

Failure injection (for demonstrating IGuard) lives under /_demo/* and is only enabled when
DEMO_CONTROL_ENABLED=true. Injected state is in-process memory, so a real container restart clears
it - exactly what the recovery engine demonstration relies on.
"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NAME = os.environ.get("SERVICE_NAME", "game-api")
ENV = os.environ.get("IGUARD_ENV", "development")
CONTROL = os.environ.get("DEMO_CONTROL_ENABLED", "false").lower() == "true"
PORT = int(os.environ.get("PORT", "8080"))
START = time.time()

state = {"mode": "ok", "delay_ms": 0}  # mode: ok | down (HTTP 503) | error (HTTP 500)
lock = threading.Lock()
PLAYERS = ["nova", "atlas", "pixel", "ember", "cobalt", "lyra", "onyx", "juno", "echo", "zephyr"]


def log(severity: str, message: str, **extra: object) -> None:
    rec = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "severity": severity, "service": NAME, "environment": ENV,
        "request_id": extra.pop("request_id", "-"), "correlation_id": extra.pop("correlation_id", "-"),
        "message": message, **extra,
    }
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()


def payload(path: str) -> tuple[int, str, bytes]:
    """Realistic but synthetic responses per personality."""
    rnd = random.Random(int(time.time() // 10))
    if NAME == "game-web" and path in ("/", "/index.html"):
        html = ("<!doctype html><title>Demo Casino (synthetic)</title><h1>Demo Casino</h1>"
                "<p>Synthetic demo front-end. No real money, no real games.</p>")
        return 200, "text/html; charset=utf-8", html.encode()
    if NAME == "game-api" and path == "/api/v1/games":
        games = [{"id": f"g{i}", "name": n, "rtp_demo": round(95 + rnd.random(), 2), "players_online": rnd.randint(5, 400)}
                 for i, n in enumerate(["Demo Slots", "Demo Roulette", "Demo Blackjack", "Demo Poker"])]
        return 200, "application/json", json.dumps({"synthetic": True, "games": games}).encode()
    if NAME == "wallet-mock" and path == "/api/v1/wallet/balance":
        return 200, "application/json", json.dumps({"synthetic": True, "currency": "DEMO", "balance": round(rnd.random() * 1000, 2)}).encode()
    if NAME == "authentication-service" and path == "/api/v1/auth/session":
        return 200, "application/json", json.dumps({"synthetic": True, "session": uuid.uuid4().hex, "ttl": 900}).encode()
    if NAME == "leaderboard-service" and path == "/api/v1/leaderboard":
        rows = sorted(({"player": p, "score": rnd.randint(1000, 99999)} for p in PLAYERS), key=lambda r: -r["score"])[:5]
        return 200, "application/json", json.dumps({"synthetic": True, "top": rows}).encode()
    return 404, "application/json", b'{"error":"not found"}'


class Handler(BaseHTTPRequestHandler):
    server_version = "iguard-demo"

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        log("ERROR" if code >= 500 else "INFO", "request", method=self.command, path=self.path, status=code,
            request_id=self.headers.get("X-Request-ID", "-"))

    def _apply_state(self) -> bool:
        with lock:
            mode, delay = state["mode"], state["delay_ms"]
        if delay:
            time.sleep(delay / 1000)
        if mode == "down":
            self._send(503, b'{"status":"unavailable","reason":"injected failure"}')
            return False
        if mode == "error":
            self._send(500, b'{"status":"error","reason":"injected failure"}')
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            if self._apply_state():
                self._send(200, json.dumps({"status": "ok", "service": NAME, "uptime_s": int(time.time() - START),
                                            "synthetic": True}).encode())
            return
        if self._apply_state():
            code, ctype, body = payload(path)
            self._send(code, body, ctype)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/_demo/") or not CONTROL:
            return self._send(404, b'{"error":"not found"}')
        q = parse_qs(parsed.query)
        action = parsed.path.removeprefix("/_demo/")
        with lock:
            if action == "fail":
                state["mode"] = "error" if q.get("kind", ["down"])[0] == "error" else "down"
            elif action == "slow":
                state["delay_ms"] = max(0, min(int(q.get("ms", ["2000"])[0]), 10000))
            elif action == "heal":
                state.update(mode="ok", delay_ms=0)
            else:
                return self._send(404, b'{"error":"unknown control action"}')
            snapshot = dict(state)
        log("WARNING", "demo control invoked", action=action, state=snapshot)
        self._send(200, json.dumps({"ok": True, "state": snapshot}).encode())


def main() -> None:
    log("INFO", "demo service starting", port=PORT, control_enabled=CONTROL)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104


if __name__ == "__main__":
    main()
