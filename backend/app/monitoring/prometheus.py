"""Thin Prometheus HTTP API client. Missing data is None - never coerced to zero."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamUnavailable


@dataclass
class Sample:
    labels: dict[str, str]
    value: float
    timestamp: float


class PrometheusClient:
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.prometheus_url).rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout or s.integration_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            resp = self._client.get(path, params=params)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamUnavailable(
                "Prometheus is unavailable", details=str(type(exc).__name__)
            ) from exc
        if body.get("status") != "success":
            raise UpstreamUnavailable("Prometheus query failed", details=body.get("error"))
        return body["data"]

    def query(self, expr: str) -> list[Sample]:
        data = self._get("/api/v1/query", {"query": expr})
        out: list[Sample] = []
        for item in data.get("result", []):
            ts, raw = item["value"]
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isnan(val) or math.isinf(val):
                continue  # NaN means "no data" in PromQL; treat as missing
            out.append(Sample(item.get("metric", {}), val, float(ts)))
        return out

    def scalar(self, expr: str) -> float | None:
        samples = self.query(expr)
        return samples[0].value if samples else None

    def by_label(self, expr: str, label: str = "instance") -> dict[str, float]:
        return {s.labels.get(label, ""): s.value for s in self.query(expr)}

    def query_range(self, expr: str, start: float, end: float, step: int) -> list[dict[str, Any]]:
        data = self._get(
            "/api/v1/query_range", {"query": expr, "start": start, "end": end, "step": step}
        )
        series = []
        for item in data.get("result", []):
            points = []
            for ts, raw in item.get("values", []):
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                if not (math.isnan(val) or math.isinf(val)):
                    points.append({"t": float(ts), "v": val})
            series.append({"labels": item.get("metric", {}), "points": points})
        return series

    def targets(self) -> list[dict[str, Any]]:
        data = self._get("/api/v1/targets", {"state": "active"})
        return [
            {
                "job": t["labels"].get("job"),
                "instance": t["labels"].get("instance"),
                "health": t.get("health"),
                "last_error": t.get("lastError") or None,
                "last_scrape": t.get("lastScrape"),
            }
            for t in data.get("activeTargets", [])
        ]

    def is_available(self) -> bool:
        try:
            resp = self._client.get("/-/healthy")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


# --- PromQL used by the platform. Recording rules are defined in monitoring/prometheus/rules. ---
Q_CPU = "iguard:node_cpu_usage_percent"
Q_MEM = "iguard:node_memory_usage_percent"
Q_DISK = "iguard:node_disk_usage_percent"
Q_UP = "up"
Q_CONTAINER_LAST_SEEN = 'time() - container_last_seen{name!=""}'
Q_CONTAINER_RESTARTS = 'changes(container_start_time_seconds{name!=""}[10m])'


def instance_selector(instance: str) -> str:
    """Safely embed an instance label value into PromQL."""
    escaped = instance.replace("\\", "\\\\").replace('"', '\\"')
    return f'instance="{escaped}"'


def node_metrics(prom: PrometheusClient, instance: str) -> dict[str, Any]:
    sel = instance_selector(instance)
    q = prom.scalar
    mem_total = q(f"node_memory_MemTotal_bytes{{{sel}}}")
    mem_avail = q(f"node_memory_MemAvailable_bytes{{{sel}}}")
    mem_used = mem_total - mem_avail if mem_total is not None and mem_avail is not None else None
    disk_total = q(
        f'node_filesystem_size_bytes{{{sel},mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}}'
    )
    disk_free = q(
        f'node_filesystem_avail_bytes{{{sel},mountpoint="/",fstype!~"tmpfs|overlay|squashfs"}}'
    )
    boot = q(f"node_boot_time_seconds{{{sel}}}")
    info = prom.query(f"node_uname_info{{{sel}}}")
    return {
        "instance": instance,
        "cpu_usage_percent": q(f"{Q_CPU}{{{sel}}}"),
        "load1": q(f"node_load1{{{sel}}}"),
        "load5": q(f"node_load5{{{sel}}}"),
        "load15": q(f"node_load15{{{sel}}}"),
        "cpu_cores": q(f'count(node_cpu_seconds_total{{{sel},mode="idle"}})'),
        "memory_total_bytes": mem_total,
        "memory_available_bytes": mem_avail,
        "memory_used_bytes": mem_used,
        "memory_usage_percent": q(f"{Q_MEM}{{{sel}}}"),
        "disk_total_bytes": disk_total,
        "disk_free_bytes": disk_free,
        "disk_usage_percent": q(f"{Q_DISK}{{{sel}}}"),
        "disk_io_utilization_percent": _times(
            q(f"max(rate(node_disk_io_time_seconds_total{{{sel}}}[2m]))"), 100
        ),
        "disk_read_bytes_per_sec": q(f"sum(rate(node_disk_read_bytes_total{{{sel}}}[2m]))"),
        "disk_write_bytes_per_sec": q(f"sum(rate(node_disk_written_bytes_total{{{sel}}}[2m]))"),
        "network_receive_bytes_per_sec": q(
            f'sum(rate(node_network_receive_bytes_total{{{sel},device!~"lo|veth.*|docker.*|br-.*"}}[2m]))'
        ),
        "network_transmit_bytes_per_sec": q(
            f'sum(rate(node_network_transmit_bytes_total{{{sel},device!~"lo|veth.*|docker.*|br-.*"}}[2m]))'
        ),
        "network_receive_errors_per_sec": q(
            f'sum(rate(node_network_receive_errs_total{{{sel},device!~"lo|veth.*|docker.*|br-.*"}}[2m]))'
        ),
        "network_transmit_errors_per_sec": q(
            f'sum(rate(node_network_transmit_errs_total{{{sel},device!~"lo|veth.*|docker.*|br-.*"}}[2m]))'
        ),
        "network_receive_drops_per_sec": q(
            f'sum(rate(node_network_receive_drop_total{{{sel},device!~"lo|veth.*|docker.*|br-.*"}}[2m]))'
        ),
        "network_transmit_drops_per_sec": q(
            f'sum(rate(node_network_transmit_drop_total{{{sel},device!~"lo|veth.*|docker.*|br-.*"}}[2m]))'
        ),
        "uptime_seconds": (time.time() - boot) if boot is not None else None,
        "host": (
            {
                "hostname": info[0].labels.get("nodename"),
                "kernel": info[0].labels.get("release"),
                "machine": info[0].labels.get("machine"),
                "os": info[0].labels.get("sysname"),
            }
            if info
            else None
        ),
        "per_core_cpu_percent": [
            {"cpu": s.labels.get("cpu"), "usage_percent": s.value}
            for s in sorted(
                prom.query(f"iguard:node_cpu_core_usage_percent{{{sel}}}"),
                key=lambda x: int(x.labels.get("cpu", "0") or 0),
            )
        ],
        "filesystems": [
            {
                "mountpoint": s.labels.get("mountpoint"),
                "fstype": s.labels.get("fstype"),
                "usage_percent": s.value,
            }
            for s in prom.query(
                f'100 - (node_filesystem_avail_bytes{{{sel},fstype!~"tmpfs|overlay|squashfs|devtmpfs|rootfs"}}'
                f' / node_filesystem_size_bytes{{{sel},fstype!~"tmpfs|overlay|squashfs|devtmpfs|rootfs"}} * 100)'
            )
        ],
    }


def _times(v: float | None, n: float) -> float | None:
    return None if v is None else v * n


RANGE_QUERIES = {
    "cpu": "iguard:node_cpu_usage_percent{%s}",
    "memory": "iguard:node_memory_usage_percent{%s}",
    "disk": "iguard:node_disk_usage_percent{%s}",
    "network_rx": 'sum(rate(node_network_receive_bytes_total{%s,device!~"lo|veth.*|docker.*|br-.*"}[2m]))',
    "network_tx": 'sum(rate(node_network_transmit_bytes_total{%s,device!~"lo|veth.*|docker.*|br-.*"}[2m]))',
    "load1": "node_load1{%s}",
}
