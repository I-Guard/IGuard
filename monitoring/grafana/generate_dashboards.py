#!/usr/bin/env python3
"""Generates the provisioned Grafana dashboards (grafana/dashboards/*.json).

Every panel queries the real Prometheus (uid iguard-prometheus) or Loki (uid iguard-loki) data
source - nothing is static. Run:  python3 monitoring/grafana/generate_dashboards.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
PROM = {"type": "prometheus", "uid": "iguard-prometheus"}
LOKI = {"type": "loki", "uid": "iguard-loki"}


def target(expr: str, legend: str = "", ds: dict | None = None, ref: str = "A", instant: bool = False) -> dict:
    t = {"refId": ref, "datasource": ds or PROM, "expr": expr, "legendFormat": legend}
    if instant:
        t["instant"] = True
    return t


class Dash:
    def __init__(self, uid: str, title: str, tags: list[str], variables: list[dict] | None = None):
        self.d = {
            "uid": uid, "title": title, "tags": ["iguard", *tags], "timezone": "browser",
            "schemaVersion": 39, "version": 1, "editable": False, "refresh": "30s",
            "time": {"from": "now-1h", "to": "now"}, "annotations": {"list": []},
            "templating": {"list": variables or []}, "panels": [],
        }
        self._id, self._x, self._y, self._rowh = 1, 0, 0, 0

    def _place(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._x, self._y, self._rowh = 0, self._y + self._rowh, 0
        pos = {"x": self._x, "y": self._y, "w": w, "h": h}
        self._x += w
        self._rowh = max(self._rowh, h)
        return pos

    def _add(self, panel: dict, w: int, h: int) -> None:
        panel.update({"id": self._id, "gridPos": self._place(w, h)})
        self._id += 1
        self.d["panels"].append(panel)

    def timeseries(self, title: str, targets: list[dict], unit: str = "short", w: int = 12, h: int = 8,
                   mn: float | None = None, mx: float | None = None) -> None:
        defaults = {"unit": unit, "custom": {"spanNulls": False, "lineWidth": 1, "fillOpacity": 8}}
        if mn is not None:
            defaults["min"] = mn
        if mx is not None:
            defaults["max"] = mx
        self._add({"type": "timeseries", "title": title, "datasource": targets[0]["datasource"],
                   "targets": targets, "fieldConfig": {"defaults": defaults, "overrides": []},
                   "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]},
                               "tooltip": {"mode": "multi"}}}, w, h)

    def stat(self, title: str, expr: str, unit: str = "short", w: int = 4, h: int = 4,
             thresholds: list[tuple[float | None, str]] | None = None, mappings: list | None = None) -> None:
        steps = [{"color": c, "value": v} for v, c in (thresholds or [(None, "green")])]
        self._add({"type": "stat", "title": title, "datasource": PROM,
                   "targets": [target(expr, instant=True)],
                   "fieldConfig": {"defaults": {"unit": unit, "noValue": "no data",
                                                "thresholds": {"mode": "absolute", "steps": steps},
                                                "mappings": mappings or []}, "overrides": []},
                   "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"}}, w, h)

    def gauge(self, title: str, expr: str, w: int = 6, h: int = 6) -> None:
        self._add({"type": "gauge", "title": title, "datasource": PROM, "targets": [target(expr, instant=True)],
                   "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100, "noValue": "no data",
                                                "thresholds": {"mode": "absolute", "steps": [
                                                    {"color": "green", "value": None}, {"color": "orange", "value": 80},
                                                    {"color": "red", "value": 90}]}}, "overrides": []},
                   "options": {"reduceOptions": {"calcs": ["lastNotNull"]}}}, w, h)

    def table(self, title: str, expr: str, w: int = 24, h: int = 8) -> None:
        self._add({"type": "table", "title": title, "datasource": PROM,
                   "targets": [{**target(expr, instant=True), "format": "table"}],
                   "fieldConfig": {"defaults": {"noValue": "no data"}, "overrides": []},
                   "options": {"showHeader": True}}, w, h)

    def logs(self, title: str, expr: str, w: int = 24, h: int = 12) -> None:
        self._add({"type": "logs", "title": title, "datasource": LOKI,
                   "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "queryType": "range"}],
                   "options": {"showTime": True, "wrapLogMessage": True, "enableLogDetails": True,
                               "sortOrder": "Descending"}}, w, h)

    def save(self, name: str) -> None:
        OUT.mkdir(exist_ok=True)
        (OUT / f"{name}.json").write_text(json.dumps(self.d, indent=2) + "\n")


UP_MAP = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]


def instance_var(metric: str = "node_uname_info") -> dict:
    return {"name": "instance", "type": "query", "datasource": PROM, "label": "Host", "refresh": 2,
            "query": {"query": f"label_values({metric}, instance)", "refId": "v"}, "includeAll": True,
            "multi": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"}}


def main() -> None:
    # 1 -------------------------------------------------------------- Infrastructure Overview
    d = Dash("iguard-infra-overview", "Infrastructure Overview", ["infrastructure"])
    d.stat("Scrape targets up", 'count(up == 1)', w=4)
    d.stat("Scrape targets down", 'count(up == 0) or vector(0)', w=4,
           thresholds=[(None, "green"), (1, "red")])
    d.stat("Containers (cAdvisor)", 'count(container_last_seen{name!=""})', w=4)
    d.stat("Firing alerts", 'count(ALERTS{alertstate="firing"}) or vector(0)', w=4,
           thresholds=[(None, "green"), (1, "orange"), (3, "red")])
    d.stat("Avg CPU", 'avg(iguard:node_cpu_usage_percent)', "percent", 4,
           thresholds=[(None, "green"), (80, "orange"), (90, "red")])
    d.stat("Avg memory", 'avg(iguard:node_memory_usage_percent)', "percent", 4,
           thresholds=[(None, "green"), (80, "orange"), (92, "red")])
    d.gauge("Root disk usage", "max(iguard:node_disk_usage_percent)", 8)
    d.timeseries("CPU usage", [target("iguard:node_cpu_usage_percent", "{{instance}}")], "percent", 8, mn=0, mx=100)
    d.timeseries("Memory usage", [target("iguard:node_memory_usage_percent", "{{instance}}")], "percent", 8, mn=0, mx=100)
    d.table("Scrape target health", "up", h=8)
    d.save("infrastructure-overview")

    # 2 -------------------------------------------------------------- Linux Server Monitoring
    d = Dash("iguard-linux", "Linux Server Monitoring", ["linux", "node-exporter"], [instance_var()])
    sel = 'instance=~"$instance"'
    nd = 'device!~"lo|veth.*|docker.*|br-.*"'
    d.gauge("CPU %", f'avg(iguard:node_cpu_usage_percent{{{sel}}})', 6)
    d.gauge("Memory %", f'avg(iguard:node_memory_usage_percent{{{sel}}})', 6)
    d.gauge("Root disk %", f'max(iguard:node_disk_usage_percent{{{sel}}})', 6)
    d.stat("Uptime", f'time() - max(node_boot_time_seconds{{{sel}}})', "s", 6, 6)
    d.timeseries("CPU usage (host)", [target(f'iguard:node_cpu_usage_percent{{{sel}}}', "{{instance}}")], "percent", mn=0, mx=100)
    d.timeseries("CPU per core", [target(f'iguard:node_cpu_core_usage_percent{{{sel}}}', "{{instance}} cpu{{cpu}}")], "percent", mn=0, mx=100)
    d.timeseries("Load average", [target(f'node_load1{{{sel}}}', "1m {{instance}}", ref="A"),
                                   target(f'node_load5{{{sel}}}', "5m {{instance}}", ref="B"),
                                   target(f'node_load15{{{sel}}}', "15m {{instance}}", ref="C")])
    d.timeseries("Memory", [target(f'node_memory_MemTotal_bytes{{{sel}}}', "total {{instance}}", ref="A"),
                             target(f'node_memory_MemTotal_bytes{{{sel}}} - node_memory_MemAvailable_bytes{{{sel}}}', "used {{instance}}", ref="B"),
                             target(f'node_memory_MemAvailable_bytes{{{sel}}}', "available {{instance}}", ref="C")], "bytes")
    d.timeseries("Filesystem usage", [target(
        f'100 - node_filesystem_avail_bytes{{{sel},fstype!~"tmpfs|overlay|squashfs|devtmpfs|rootfs"}} / '
        f'node_filesystem_size_bytes{{{sel},fstype!~"tmpfs|overlay|squashfs|devtmpfs|rootfs"}} * 100',
        "{{instance}} {{mountpoint}}")], "percent", mn=0, mx=100)
    d.timeseries("Disk I/O throughput", [target(f'sum by (instance) (rate(node_disk_read_bytes_total{{{sel}}}[2m]))', "read {{instance}}", ref="A"),
                                          target(f'sum by (instance) (rate(node_disk_written_bytes_total{{{sel}}}[2m]))', "write {{instance}}", ref="B")], "Bps")
    d.timeseries("Disk I/O utilisation", [target(f'max by (instance) (rate(node_disk_io_time_seconds_total{{{sel}}}[2m])) * 100', "{{instance}}")], "percent", mn=0)
    d.timeseries("Network throughput", [target(f'sum by (instance) (rate(node_network_receive_bytes_total{{{sel},{nd}}}[2m]))', "rx {{instance}}", ref="A"),
                                         target(f'sum by (instance) (rate(node_network_transmit_bytes_total{{{sel},{nd}}}[2m]))', "tx {{instance}}", ref="B")], "Bps")
    d.timeseries("Network errors & drops", [
        target(f'sum by (instance) (rate(node_network_receive_errs_total{{{sel},{nd}}}[2m]))', "rx errors {{instance}}", ref="A"),
        target(f'sum by (instance) (rate(node_network_transmit_errs_total{{{sel},{nd}}}[2m]))', "tx errors {{instance}}", ref="B"),
        target(f'sum by (instance) (rate(node_network_receive_drop_total{{{sel},{nd}}}[2m]))', "rx drops {{instance}}", ref="C"),
        target(f'sum by (instance) (rate(node_network_transmit_drop_total{{{sel},{nd}}}[2m]))', "tx drops {{instance}}", ref="D")], "pps")
    d.table("Host information", f'node_uname_info{{{sel}}}', h=6)
    d.save("linux-server-monitoring")

    # 3 -------------------------------------------------------------- Docker Container Monitoring
    cv = {"name": "container", "type": "query", "datasource": PROM, "label": "Container", "refresh": 2,
          "query": {"query": 'label_values(container_last_seen{name!=""}, name)', "refId": "v"},
          "includeAll": True, "multi": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"}}
    d = Dash("iguard-containers", "Docker Container Monitoring", ["docker", "cadvisor"], [cv])
    c = 'name=~"$container"'
    d.stat("Running containers", 'count(container_last_seen{name!=""})', w=6)
    d.stat("Restarts (1h)", f'sum(changes(container_start_time_seconds{{{c}}}[1h])) or vector(0)', w=6,
           thresholds=[(None, "green"), (1, "orange"), (5, "red")])
    d.stat("Total container CPU", f'sum(iguard:container_cpu_usage_cores{{{c}}})', "none", 6)
    d.stat("Total container memory", f'sum(iguard:container_memory_working_set_bytes{{{c}}})', "bytes", 6)
    d.timeseries("CPU per container (cores)", [target(f'iguard:container_cpu_usage_cores{{{c}}}', "{{name}}")], "none")
    d.timeseries("Memory working set", [target(f'iguard:container_memory_working_set_bytes{{{c}}}', "{{name}}")], "bytes")
    d.timeseries("Network receive", [target(f'sum by (name) (rate(container_network_receive_bytes_total{{{c}}}[2m]))', "{{name}}")], "Bps")
    d.timeseries("Network transmit", [target(f'sum by (name) (rate(container_network_transmit_bytes_total{{{c}}}[2m]))', "{{name}}")], "Bps")
    d.timeseries("Container restarts (10m)", [target(f'changes(container_start_time_seconds{{{c}}}[10m])', "{{name}}")], w=12)
    d.timeseries("Seconds since last seen", [target(f'time() - container_last_seen{{{c}}}', "{{name}}")], "s", w=12)
    d.save("docker-container-monitoring")

    # 4 -------------------------------------------------------------- Application Health
    d = Dash("iguard-app-health", "Application Health", ["application", "blackbox"])
    d.table("Endpoint status (1 = up)", 'probe_success{job="blackbox-http"}', h=7)
    d.stat("Endpoints up", 'count(probe_success{job="blackbox-http"} == 1)', w=6)
    d.stat("Endpoints down", 'count(probe_success{job="blackbox-http"} == 0) or vector(0)', w=6,
           thresholds=[(None, "green"), (1, "red")])
    d.stat("Availability (1h)", 'avg(avg_over_time(probe_success{job="blackbox-http"}[1h])) * 100', "percent", 6,
           thresholds=[(None, "red"), (95, "orange"), (99, "green")])
    d.stat("TCP ports open", 'count(probe_success{job="blackbox-tcp"} == 1)', w=6)
    d.timeseries("Probe success", [target('probe_success{job="blackbox-http"}', "{{instance}}")], mn=0, mx=1)
    d.timeseries("HTTP status code", [target('probe_http_status_code{job="blackbox-http"}', "{{instance}}")])
    d.timeseries("TLS / redirects", [target('probe_http_redirects{job="blackbox-http"}', "redirects {{instance}}")], w=12)
    d.timeseries("DNS + connect time", [target('probe_dns_lookup_time_seconds{job="blackbox-http"}', "dns {{instance}}", ref="A"),
                                         target('probe_http_duration_seconds{job="blackbox-http",phase="connect"}', "connect {{instance}}", ref="B")], "s", w=12)
    d.save("application-health")

    # 5 -------------------------------------------------------------- API Latency and Availability
    d = Dash("iguard-api-latency", "API Latency and Availability", ["api", "latency", "slo"])
    d.stat("Availability 24h", 'avg(avg_over_time(probe_success{job="blackbox-http"}[24h])) * 100', "percent", 6,
           thresholds=[(None, "red"), (95, "orange"), (99.5, "green")])
    d.stat("p95 probe latency", 'quantile(0.95, probe_duration_seconds{job="blackbox-http"})', "s", 6,
           thresholds=[(None, "green"), (0.5, "orange"), (1, "red")])
    d.stat("Slowest endpoint", 'max(probe_duration_seconds{job="blackbox-http"})', "s", 6)
    d.stat("Failed probes (1h)", 'sum(count_over_time((probe_success{job="blackbox-http"} == 0)[1h:15s])) or vector(0)', w=6)
    d.timeseries("Response time per endpoint", [target('probe_duration_seconds{job="blackbox-http"}', "{{instance}}")], "s")
    d.timeseries("Response time (5m avg)", [target('avg_over_time(probe_duration_seconds{job="blackbox-http"}[5m])', "{{instance}}")], "s")
    d.timeseries("Availability per endpoint (1h)", [target('avg_over_time(probe_success{job="blackbox-http"}[1h]) * 100', "{{instance}}")], "percent", mn=0, mx=100)
    d.timeseries("Phase timings", [target('sum by (phase) (probe_http_duration_seconds{job="blackbox-http"})', "{{phase}}")], "s")
    d.save("api-latency-availability")

    # 6 -------------------------------------------------------------- Incident and Alert Overview
    d = Dash("iguard-incidents", "Incident and Alert Overview", ["incidents", "alerts"])
    d.stat("Firing alerts", 'count(ALERTS{alertstate="firing"}) or vector(0)', w=6,
           thresholds=[(None, "green"), (1, "orange"), (3, "red")])
    d.stat("Critical firing", 'count(ALERTS{alertstate="firing",severity="critical"}) or vector(0)', w=6,
           thresholds=[(None, "green"), (1, "red")])
    d.stat("Pending alerts", 'count(ALERTS{alertstate="pending"}) or vector(0)', w=6)
    d.stat("Alertmanager notifications failed (1h)", 'sum(increase(alertmanager_notifications_failed_total[1h])) or vector(0)', w=6,
           thresholds=[(None, "green"), (1, "red")])
    d.timeseries("Firing alerts over time", [target('count by (alertname) (ALERTS{alertstate="firing"})', "{{alertname}}")])
    d.timeseries("Alerts by severity", [target('count by (severity) (ALERTS{alertstate="firing"})', "{{severity}}")])
    d.table("Currently active alerts", 'ALERTS{alertstate=~"firing|pending"}', h=9)
    d.timeseries("Notifications sent by Alertmanager", [target('sum by (integration) (increase(alertmanager_notifications_total[10m]))', "{{integration}}")], w=24, h=7)
    d.logs("IGuard incident / recovery log events",
           '{service="backend"} | json | message=~"incident.*|recovery.*|notification.*"', h=10)
    d.save("incident-alert-overview")

    # 7 -------------------------------------------------------------- Centralized Logs
    sv = {"name": "service", "type": "query", "datasource": LOKI, "label": "Service", "refresh": 2,
          "query": {"label": "service", "refId": "v", "stream": "", "type": 1}, "includeAll": True, "multi": True,
          "allValue": ".+", "current": {"text": "All", "value": "$__all"}}
    lv = {"name": "level", "type": "custom", "label": "Level", "query": "debug,info,warning,error,critical",
          "includeAll": True, "multi": True, "allValue": ".+", "current": {"text": "All", "value": "$__all"}}
    txt = {"name": "search", "type": "textbox", "label": "Contains", "query": "", "current": {"text": "", "value": ""}}
    d = Dash("iguard-logs", "Centralized Logs", ["logs", "loki"], [sv, lv, txt])
    sel = '{service=~"$service", level=~"$level"} |~ "(?i)$search"'
    d._add({"type": "timeseries", "title": "Log volume by level", "datasource": LOKI,
            "targets": [{"refId": "A", "datasource": LOKI, "queryType": "range", "legendFormat": "{{level}}",
                         "expr": 'sum by (level) (count_over_time({service=~"$service", level=~"$level"}[$__interval]))'}],
            "fieldConfig": {"defaults": {"unit": "short", "custom": {"drawStyle": "bars", "stacking": {"mode": "normal"}, "fillOpacity": 60}}, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}}}, 24, 7)
    d._add({"type": "timeseries", "title": "Errors by service", "datasource": LOKI,
            "targets": [{"refId": "A", "datasource": LOKI, "queryType": "range", "legendFormat": "{{service}}",
                         "expr": 'sum by (service) (count_over_time({service=~"$service", level=~"error|critical"}[$__interval]))'}],
            "fieldConfig": {"defaults": {"unit": "short", "custom": {"drawStyle": "bars", "fillOpacity": 60}}, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}}}, 24, 6)
    d.logs("Logs", sel, h=16)
    d.save("centralized-logs")


if __name__ == "__main__":
    main()
