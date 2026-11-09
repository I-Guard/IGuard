import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path

import httpx
import pytest

from app.core.errors import UpstreamUnavailable, ValidationFailed
from app.models import Service
from app.models.enums import ActionType, CheckType
from app.monitoring import checker
from app.monitoring.loki import LokiClient, build_query
from app.monitoring.prometheus import PrometheusClient, instance_selector
from app.recovery.adapters import AgentAdapter, SimulatedAdapter, parse_heal_map, sign


def svc(**kw):
    base = dict(
        name="s",
        check_type=CheckType.HTTP,
        url="http://app:8080/health",
        timeout_seconds=1.0,
        expected_status_codes=[200],
        retry_threshold=3,
        latency_threshold_ms=100,
    )
    base.update(kw)
    return Service(**base)


# ---------------------------------------------------------------- checker / SSRF
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/",
        "http://[fe80::1]/",
        "http://user:pw@app/health",
        "ftp://app/x",
        "http://0.0.0.0/",
    ],
)
def test_ssrf_targets_blocked(url):
    out = checker.run_check(
        svc(url=url), transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    assert out.success is False and (out.error or "").startswith("Blocked target")


def test_private_ranges_allowed_for_internal_monitoring():
    out = checker.run_check(
        svc(url="http://10.1.2.3/health"),
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    assert out.success


def test_http_check_status_codes_and_latency():
    ok = checker.run_check(svc(), transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert ok.success and ok.response_time_ms is not None and ok.status_code == 200
    bad = checker.run_check(svc(), transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert not bad.success and bad.status_code == 503 and "503" in bad.error
    custom = checker.run_check(
        svc(expected_status_codes=[204]),
        transport=httpx.MockTransport(lambda r: httpx.Response(204)),
    )
    assert custom.success


def test_http_check_does_not_follow_redirects_or_leak_exceptions():
    seen = []

    def handler(r):
        seen.append(str(r.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    out = checker.run_check(svc(), transport=httpx.MockTransport(handler))
    assert not out.success and len(seen) == 1


def test_timeout_and_connection_errors_are_reported():
    def boom(r):
        raise httpx.ConnectTimeout("t")

    assert (
        checker.run_check(svc(), transport=httpx.MockTransport(boom)).error == "Request timed out"
    )

    def refused(r):
        raise httpx.ConnectError("secret-host-details")

    out = checker.run_check(svc(), transport=httpx.MockTransport(refused))
    assert not out.success and "secret-host-details" not in out.error


def test_tcp_check_real_socket():
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        out = checker.run_check(
            svc(check_type=CheckType.TCP, url=None, host="127.0.0.1", port=port)
        )
        assert out.success
    finally:
        s.close()
    dead = checker.run_check(svc(check_type=CheckType.TCP, url=None, host="127.0.0.1", port=port))
    assert not dead.success


# ---------------------------------------------------------------- Loki query building
def test_loki_query_builder_escapes_and_allowlists():
    assert build_query({"service": "game-api"}) == '{service="game-api"}'
    q = build_query({"service": "game-api", "level": "error"}, 'say "hi"')
    assert q == '{service="game-api",level="error"} |= "say \\"hi\\""'
    assert build_query({}, None).startswith("{job=~")
    for evil in ('x"} |= "', "a\nb", "{}", "x" * 200):
        with pytest.raises(ValidationFailed):
            build_query({"service": evil})
    with pytest.raises(ValidationFailed):
        build_query({"__name__": "x"})
    with pytest.raises(ValidationFailed):
        build_query({}, "(", regex=True)
    with pytest.raises(ValidationFailed):
        build_query({}, "x" * 201)


def test_loki_client_parses_and_redacts():
    line = json.dumps({"message": "hi", "password": "p", "severity": "INFO"})
    body = {
        "data": {
            "result": [
                {
                    "stream": {"service": "a"},
                    "values": [
                        ["1700000000000000000", line],
                        ["1700000001000000000", "plain Bearer abc.def.ghi"],
                    ],
                }
            ]
        }
    }
    c = LokiClient(
        "http://loki", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    )
    rows = c.query_range('{job=~".+"}', limit=10)
    assert rows[0]["line"].endswith("***REDACTED***") and "abc.def.ghi" not in rows[0]["line"]
    assert rows[1]["fields"]["password"] == "***REDACTED***"


def test_loki_outage_maps_to_503():
    def boom(r):
        raise httpx.ConnectError("x")

    with pytest.raises(UpstreamUnavailable):
        LokiClient("http://loki", transport=httpx.MockTransport(boom)).query_range('{a="b"}')


# ---------------------------------------------------------------- Prometheus client
def prom_with(result, status="success"):
    return PrometheusClient(
        "http://p",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"status": status, "data": {"result": result}})
        ),
    )


def test_prometheus_nan_and_missing_are_none_not_zero():
    p = prom_with([{"metric": {}, "value": [1, "NaN"]}])
    assert p.scalar("x") is None
    assert prom_with([]).scalar("x") is None
    assert prom_with([{"metric": {"instance": "a"}, "value": [1, "42.5"]}]).by_label("x") == {
        "a": 42.5
    }


def test_prometheus_error_status_and_outage():
    with pytest.raises(UpstreamUnavailable):
        prom_with([], status="error").query("x")

    def boom(r):
        raise httpx.ConnectError("x")

    with pytest.raises(UpstreamUnavailable):
        PrometheusClient("http://p", transport=httpx.MockTransport(boom)).query("x")


def test_promql_label_escaping():
    assert instance_selector('a"b\\c') == 'instance="a\\"b\\\\c"'


# ---------------------------------------------------------------- recovery adapters
def test_agent_adapter_signs_requests_and_handles_failures():
    captured = {}

    def handler(req):
        captured["headers"], captured["body"] = req.headers, req.read()
        return httpx.Response(200, json={"ok": True, "output": "done"})

    a = AgentAdapter("http://agent", "s" * 20, httpx.MockTransport(handler))
    r = a.execute(ActionType.CONTAINER_RESTART, "app-x", dry_run=False, timeout=5, request_id="r1")
    assert r.ok and r.output == "done"
    ts, sig = captured["headers"]["x-iguard-timestamp"], captured["headers"]["x-iguard-signature"]
    assert hmac.compare_digest(sig, sign("s" * 20, ts, captured["body"]))
    body = json.loads(captured["body"])
    assert body["target"] == "app-x" and "command" not in body and "shell" not in body

    down = AgentAdapter(
        "http://agent",
        "s" * 20,
        httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))),
    )
    assert not down.execute(
        ActionType.CONTAINER_RESTART, "a", dry_run=False, timeout=1, request_id="r"
    ).ok
    denied = AgentAdapter(
        "http://agent",
        "s" * 20,
        httpx.MockTransport(
            lambda r: httpx.Response(403, json={"ok": False, "error": "not allowlisted"})
        ),
    )
    res = denied.execute(
        ActionType.CONTAINER_RESTART, "a", dry_run=False, timeout=1, request_id="r"
    )
    assert not res.ok and "allowlisted" in res.error


def test_simulated_adapter_is_a_noop_without_heal_map():
    r = SimulatedAdapter(heal_map={}).execute(
        ActionType.CONTAINER_RESTART, "x", dry_run=False, timeout=1, request_id="r"
    )
    assert r.ok and r.simulated and "no host changes" in r.output
    assert parse_heal_map("a=http://x/h, b=file:///etc/passwd, junk") == {"a": "http://x/h"}


# ---------------------------------------------------------------- the real agent module
AGENT_PATH = Path(__file__).resolve().parents[3] / "recovery" / "agent" / "agent.py"


@pytest.fixture
def agent(monkeypatch, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    ok = scripts / "ok.sh"
    ok.write_text("#!/bin/sh\necho hello $1\n")
    ok.chmod(0o755)
    fail = scripts / "fail.sh"
    fail.write_text("#!/bin/sh\nexit 3\n")
    fail.chmod(0o755)
    slow = scripts / "slow.sh"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    pol = tmp_path / "policies"
    pol.mkdir()
    (pol / "p.yaml").write_text(
        json.dumps(
            {
                "actions": [
                    {"key": "a", "action_type": "CONTAINER_RESTART", "target": "iguard-game-api"},
                    {"key": "b", "action_type": "SCRIPT", "target": "ok.sh"},
                    {"key": "c", "action_type": "SCRIPT", "target": "fail.sh"},
                    {"key": "d", "action_type": "SCRIPT", "target": "slow.sh"},
                    {"key": "e", "action_type": "CONTAINER_RESTART", "target": "iguard-postgres"},
                ]
            }
        )
    )
    monkeypatch.setenv("RECOVERY_AGENT_SECRET", "x" * 32)
    monkeypatch.setenv("RECOVERY_POLICIES_DIR", str(pol))
    monkeypatch.setenv("RECOVERY_SCRIPTS_DIR", str(scripts))
    spec = importlib.util.spec_from_file_location("iguard_agent", AGENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_allowlist_excludes_critical_and_unknown(agent):
    allow = agent.load_allowlist()
    assert ("CONTAINER_RESTART", "iguard-game-api") in allow
    assert ("CONTAINER_RESTART", "iguard-postgres") not in allow  # critical, no allow_critical
    code, payload = agent.execute(
        {"action_type": "CONTAINER_RESTART", "target": "iguard-postgres", "dry_run": False}
    )
    assert code == 403 and not payload["ok"]
    assert (
        agent.execute({"action_type": "CONTAINER_RESTART", "target": "random", "dry_run": False})[0]
        == 403
    )
    assert (
        agent.execute({"action_type": "SCRIPT", "target": "../../bin/sh", "dry_run": False})[0]
        == 403
    )


def test_agent_scripts_no_args_no_shell_timeout(agent):
    code, out = agent.execute(
        {"action_type": "SCRIPT", "target": "ok.sh", "dry_run": False, "timeout": 5}
    )
    assert (
        code == 200 and out["ok"] and out["output"].strip() == "hello"
    )  # $1 empty: no arguments passed
    assert (
        agent.execute({"action_type": "SCRIPT", "target": "fail.sh", "dry_run": False})[1]["ok"]
        is False
    )
    t0 = time.time()
    _, slow = agent.execute(
        {"action_type": "SCRIPT", "target": "slow.sh", "dry_run": False, "timeout": 1}
    )
    assert not slow["ok"] and "timed out" in slow["output"] and time.time() - t0 < 4


def test_agent_hmac_timestamp_and_replay(agent):
    body = b'{"action_type":"SCRIPT","target":"ok.sh"}'
    ts = str(int(time.time()))
    sig = hmac.new(("x" * 32).encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    hdr = {"X-IGuard-Timestamp": ts, "X-IGuard-Signature": sig}
    assert agent.verify(hdr, body) is None
    assert agent.verify(hdr, body) == "replayed request"
    assert agent.verify({**hdr, "X-IGuard-Signature": "0" * 64}, body + b" ") == "bad signature"
    old = str(int(time.time()) - 600)
    old_sig = hmac.new(("x" * 32).encode(), old.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert (
        agent.verify({"X-IGuard-Timestamp": old, "X-IGuard-Signature": old_sig}, body)
        == "stale or invalid timestamp"
    )


def test_agent_dry_run_never_calls_docker(agent, monkeypatch):
    monkeypatch.setattr(agent, "ALLOW_REAL", False)
    monkeypatch.setattr(
        agent, "docker_restart", lambda *a: pytest.fail("docker must not be called")
    )
    code, out = agent.execute(
        {"action_type": "CONTAINER_RESTART", "target": "iguard-game-api", "dry_run": True}
    )
    assert code == 200 and out["ok"] and "DRY-RUN" in out["output"]
