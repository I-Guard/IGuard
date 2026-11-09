#!/usr/bin/env python3
"""IGuard recovery agent - the ONLY component allowed to touch Docker.

Permission boundary
-------------------
* Reaches Docker exclusively through a *socket proxy* (tecnativa/docker-socket-proxy) that only
  permits ``POST /containers/{id}/restart`` and read-only container inspection. The raw
  /var/run/docker.sock is never mounted into this container or into the IGuard backend.
* Holds its OWN allowlist, loaded from the same policy YAML files (mounted read-only). A request
  is honoured only if (action_type, target) exists there, so a compromised backend still cannot
  restart arbitrary containers or run arbitrary scripts.
* Requests are authenticated with HMAC-SHA256 over ``timestamp.body`` (shared secret), rejected if
  older than 60s, and nonces are remembered to stop replays.
* Scripts are run from a fixed directory by exact file name, with NO arguments and NO shell,
  with a scrubbed environment and a hard timeout.

Stdlib only, so the image stays tiny.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml  # PyYAML (only third-party dependency)

LOG = logging.getLogger("recovery-agent")
SECRET = os.environ.get("RECOVERY_AGENT_SECRET", "")
POLICY_DIR = Path(os.environ.get("RECOVERY_POLICIES_DIR", "/policies"))
SCRIPT_DIR = Path(os.environ.get("RECOVERY_SCRIPTS_DIR", "/scripts"))
DOCKER_HOST = os.environ.get("DOCKER_PROXY_HOST", "docker-proxy")
DOCKER_PORT = int(os.environ.get("DOCKER_PROXY_PORT", "2375"))
ALLOW_REAL = os.environ.get("RECOVERY_AGENT_ENABLE_DOCKER", "true").lower() == "true"
MAX_SKEW = 60
MAX_BODY = 4096
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
CRITICAL_RE = re.compile(
    r"(postgres|database|(^|[-_.])db($|[-_.])|prometheus|grafana|loki|promtail|alertmanager|docker|"
    r"socket|iguard-backend|iguard-frontend|recovery-agent|nginx|cadvisor|node-exporter)", re.I)

_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        return json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r.created)),
                           "severity": r.levelname, "service": "recovery-agent",
                           "environment": os.environ.get("IGUARD_ENV", "development"),
                           "request_id": getattr(r, "request_id", "-"),
                           "correlation_id": getattr(r, "request_id", "-"), "message": r.getMessage()})


def load_allowlist() -> dict[tuple[str, str], dict]:
    allow: dict[tuple[str, str], dict] = {}
    for f in sorted(POLICY_DIR.glob("*.y*ml")):
        for a in (yaml.safe_load(f.read_text()) or {}).get("actions", []):
            t, k = str(a.get("target", "")), str(a.get("action_type", ""))
            if not NAME_RE.match(t) or not a.get("enabled", True):
                continue
            if k in ("CONTAINER_RESTART", "SERVICE_RESTART") and CRITICAL_RE.search(t) \
                    and not a.get("allow_critical"):
                continue
            allow[(k, t)] = a
    return allow


def verify(headers, body: bytes) -> str | None:
    if len(SECRET) < 16:
        return "agent secret not configured"
    ts, sig = headers.get("X-IGuard-Timestamp", ""), headers.get("X-IGuard-Signature", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > MAX_SKEW:
        return "stale or invalid timestamp"
    expected = hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return "bad signature"
    nonce = hashlib.sha256(body).hexdigest()
    now = time.time()
    with _nonce_lock:
        for k in [k for k, v in _nonces.items() if now - v > 2 * MAX_SKEW]:
            del _nonces[k]
        if nonce in _nonces:
            return "replayed request"
        _nonces[nonce] = now
    return None


def docker_restart(container: str, timeout: float) -> tuple[bool, str]:
    conn = http.client.HTTPConnection(DOCKER_HOST, DOCKER_PORT, timeout=timeout + 5)
    try:
        conn.request("POST", f"/containers/{container}/restart?t=10")
        resp = conn.getresponse()
        body = resp.read().decode(errors="replace")[:500]
        if resp.status == 204:
            return True, f"container '{container}' restarted"
        return False, f"docker proxy returned {resp.status}: {body}"
    except OSError as exc:
        return False, f"docker proxy unreachable: {type(exc).__name__}"
    finally:
        conn.close()


def docker_exists(container: str) -> bool:
    conn = http.client.HTTPConnection(DOCKER_HOST, DOCKER_PORT, timeout=5)
    try:
        conn.request("GET", f"/containers/{container}/json")
        return conn.getresponse().status == 200
    except OSError:
        return False
    finally:
        conn.close()


def run_script(name: str, timeout: float) -> tuple[bool, str]:
    path = (SCRIPT_DIR / name).resolve()
    if path.parent != SCRIPT_DIR.resolve() or not path.is_file() or not os.access(path, os.X_OK):
        return False, "script not found in allowlisted directory"
    try:
        proc = subprocess.run([str(path)], capture_output=True, text=True, timeout=timeout,  # noqa: S603
                              shell=False, env={"PATH": "/usr/local/bin:/usr/bin:/bin"}, cwd=str(SCRIPT_DIR))
    except subprocess.TimeoutExpired:
        return False, f"script timed out after {timeout}s"
    out = (proc.stdout + proc.stderr)[-2000:]
    return proc.returncode == 0, out if proc.returncode == 0 else f"exit {proc.returncode}: {out}"


def execute(req: dict) -> tuple[int, dict]:
    kind, target = str(req.get("action_type", "")), str(req.get("target", ""))
    dry = bool(req.get("dry_run", True))
    timeout = min(max(float(req.get("timeout", 30)), 1.0), 300.0)
    action = load_allowlist().get((kind, target))
    if action is None:
        return 403, {"ok": False, "error": "action/target is not in the agent allowlist"}
    if kind == "SCRIPT":
        if dry:
            return 200, {"ok": SCRIPT_DIR.joinpath(target).is_file(), "output": f"[DRY-RUN] would run script {target}"}
        ok, out = run_script(target, timeout)
        return 200, {"ok": ok, "output": out, "error": None if ok else out}
    if kind in ("CONTAINER_RESTART", "SERVICE_RESTART"):
        if dry:
            exists = docker_exists(target) if ALLOW_REAL else True
            return 200, {"ok": exists, "output": f"[DRY-RUN] would restart container '{target}'"
                         + ("" if exists else " (container not found)"),
                         "error": None if exists else "container not found"}
        if not ALLOW_REAL:
            return 200, {"ok": False, "error": "docker restarts are disabled on this agent"}
        ok, out = docker_restart(target, timeout)
        return 200, {"ok": ok, "output": out, "error": None if ok else out}
    return 400, {"ok": False, "error": "unsupported action type"}


class Handler(BaseHTTPRequestHandler):
    server_version = "iguard-agent"

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._send(200, {"status": "ok", "actions": len(load_allowlist())})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/execute":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"ok": False, "error": "invalid body size"})
        body = self.rfile.read(length)
        err = verify(self.headers, body)
        if err:
            LOG.warning("rejected request: %s", err)
            return self._send(401, {"ok": False, "error": err})
        try:
            req = json.loads(body)
        except ValueError:
            return self._send(400, {"ok": False, "error": "invalid json"})
        code, payload = execute(req)
        LOG.info("%s %s dry_run=%s -> %s ok=%s", req.get("action_type"), req.get("target"),
                 req.get("dry_run"), code, payload.get("ok"), extra={"request_id": req.get("request_id", "-")})
        self._send(code, payload)


def main() -> int:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[h])
    if len(SECRET) < 16:
        LOG.error("RECOVERY_AGENT_SECRET must be at least 16 characters")
        return 2
    LOG.info("recovery agent listening on :8088 with %d allowlisted actions", len(load_allowlist()))
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()  # noqa: S104
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
