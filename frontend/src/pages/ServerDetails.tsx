import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Meter, TimeSeriesChart } from "../components/charts";
import { HealthBadge, ServiceStatusBadge } from "../components/badges";
import { QueryBoundary, errorMessage, NoticeBanner } from "../components/feedback";
import { ConfirmDialog, Modal } from "../components/Modal";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, KeyValue, PageHeader, Select } from "../components/ui";
import { useAction, useServer, useServerMetrics, useServerRange, useServices } from "../hooks/queries";
import { api } from "../services/api";
import { DASH, formatBytes, formatDuration, formatNumber, formatRate } from "../utils/format";
import { ServerForm } from "./Servers";

const RANGES = [{ m: 30, l: "30 minutes" }, { m: 60, l: "1 hour" }, { m: 360, l: "6 hours" }, { m: 1440, l: "24 hours" }];

export default function ServerDetails() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const server = useServer(id);
  const metrics = useServerMetrics(id, !!server.data?.prometheus_instance);
  const services = useServices({ server_id: id, page_size: 100 });
  const [minutes, setMinutes] = useState(60);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const del = useAction(() => api.del(`/servers/${id}`), ["servers", "overview"]);
  const cpu = useServerRange(id, "cpu", minutes);
  const mem = useServerRange(id, "memory", minutes);
  const net = useServerRange(id, "network_rx", minutes);
  const m = metrics.data?.metrics;

  return (
    <QueryBoundary query={server}>
      {(s) => (
        <>
          <PageHeader title={s.name} subtitle={<span className="flex flex-wrap items-center gap-2"><HealthBadge health={s.health} /><Badge>{s.environment}</Badge><span>{s.hostname}</span></span>}
            actions={<>
              <Select aria-label="Time range" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>{RANGES.map((r) => <option key={r.m} value={r.m}>{r.l}</option>)}</Select>
              <Can role="ADMIN"><Button onClick={() => setEditing(true)}>Edit</Button><Button variant="danger" onClick={() => setDeleting(true)}>Delete</Button></Can>
            </>} />
          {!s.prometheus_instance && <NoticeBanner>No Prometheus instance is configured for this server, so no host metrics are available.</NoticeBanner>}
          {metrics.data && !metrics.data.available && s.prometheus_instance && <NoticeBanner>Metrics unavailable: {metrics.data.reason ?? "unknown reason"}. Values are shown as “{DASH}”, not zero.</NoticeBanner>}
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Resources">
              <div className="space-y-4">
                <Meter label="CPU" value={m?.cpu_usage_percent ?? null} />
                <Meter label="Memory" value={m?.memory_usage_percent ?? null} />
                <Meter label="Disk" value={m?.disk_usage_percent ?? null} />
                <Meter label="Disk I/O utilization" value={m?.disk_io_utilization_percent ?? null} />
              </div>
            </Card>
            <Card title="Host">
              <KeyValue items={[
                ["Hostname", s.hostname], ["IP", s.ip_address ?? DASH], ["OS", m?.host?.os ?? DASH], ["Kernel", m?.host?.kernel ?? DASH],
                ["Uptime", formatDuration(m?.uptime_seconds)], ["CPU cores", formatNumber(m?.cpu_cores)],
                ["Load 1/5/15", m ? [m.load1, m.load5, m.load15].map((v) => formatNumber(v, 2)).join(" / ") : DASH],
              ]} />
            </Card>
            <Card title="Memory, disk & network">
              <KeyValue items={[
                ["Memory used", `${formatBytes(m?.memory_used_bytes)} / ${formatBytes(m?.memory_total_bytes)}`],
                ["Disk free", `${formatBytes(m?.disk_free_bytes)} / ${formatBytes(m?.disk_total_bytes)}`],
                ["Disk read", formatRate(m?.disk_read_bytes_per_sec)], ["Disk write", formatRate(m?.disk_write_bytes_per_sec)],
                ["Net in", formatRate(m?.network_receive_bytes_per_sec)], ["Net out", formatRate(m?.network_transmit_bytes_per_sec)],
                ["Net errors (rx/tx)", `${formatNumber(m?.network_receive_errors_per_sec, 2)} / ${formatNumber(m?.network_transmit_errors_per_sec, 2)}`],
              ]} />
            </Card>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card title="CPU usage (%)"><TimeSeriesChart data={cpu.data} unit="%" max={100} /></Card>
            <Card title="Memory usage (%)"><TimeSeriesChart data={mem.data} unit="%" max={100} /></Card>
            <Card title="Network receive (bytes/s)"><TimeSeriesChart data={net.data} /></Card>
            <Card title="Filesystems">
              {m && m.filesystems.length ? <div className="space-y-3">{m.filesystems.map((f) => <div key={f.mountpoint}><div className="mb-1 text-xs text-ink-faint">{f.fstype}</div><Meter label={f.mountpoint} value={f.usage_percent} /></div>)}</div> : <p className="text-sm text-ink-dim">No filesystem data.</p>}
            </Card>
          </div>
          <Card className="mt-4" title="Services on this server" padded={false}>
            <QueryBoundary query={services}>{(p) => p.items.length === 0 ? <p className="p-4 text-sm text-ink-dim">No services are assigned to this server.</p> : (
              <ul className="divide-y divide-line/60">{p.items.map((sv) => <li key={sv.id}><Link to={`/services/${sv.id}`} className="flex items-center justify-between px-4 py-2.5 hover:bg-bg-hover"><span>{sv.name}</span><ServiceStatusBadge status={sv.status} /></Link></li>)}</ul>
            )}</QueryBoundary>
          </Card>
          <Modal open={editing} title="Edit server" onClose={() => setEditing(false)}><ServerForm initial={s} onDone={() => setEditing(false)} onCancel={() => setEditing(false)} /></Modal>
          <ConfirmDialog open={deleting} danger title="Delete server" confirmLabel="Delete" loading={del.isPending}
            message={<>Delete <strong>{s.name}</strong>? Its services are kept but detached from this server. This cannot be undone.</>}
            onCancel={() => setDeleting(false)}
            onConfirm={() => del.mutate(undefined, { onSuccess: () => { toast.success("Server deleted"); nav("/servers"); }, onError: (e) => { toast.error(errorMessage(e)); setDeleting(false); } })} />
        </>
      )}
    </QueryBoundary>
  );
}
