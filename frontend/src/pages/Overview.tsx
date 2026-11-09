import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { IncidentStatusBadge, SeverityBadge } from "../components/badges";
import { Donut, Meter, SimpleBars, TimeSeriesChart } from "../components/charts";
import { EmptyState, QueryBoundary } from "../components/feedback";
import { Badge, Button, Card, PageHeader, Select, StatCard, cx } from "../components/ui";
import { useOverview, useReport, useServerRange, useServers, useServices } from "../hooks/queries";
import type { Service } from "../types/api";
import { DASH, formatDuration, formatMs, formatPercent, formatRelative } from "../utils/format";
import { computePosture, recoverySuccessRate, statusRank, type PostureLevel } from "../utils/posture";

interface Summary { incidents_total: number; incidents_open: number; mttr_minutes: number | null; by_severity: Record<string, number> }
interface IncRep { per_day: { date: string; count: number }[] }

const HERO: Record<PostureLevel, { bar: string; text: string; dot: string }> = {
  operational: { bar: "border-ok/50 bg-ok/5", text: "text-ok", dot: "bg-ok" },
  degraded: { bar: "border-warn/50 bg-warn/5", text: "text-warn", dot: "bg-warn" },
  outage: { bar: "border-crit/50 bg-crit/5", text: "text-crit", dot: "bg-crit" },
  unknown: { bar: "border-line bg-bg-raised", text: "text-ink-dim", dot: "bg-ink-faint" },
};
const DOT: Record<string, string> = { UP: "bg-ok", DEGRADED: "bg-warn", DOWN: "bg-crit", UNKNOWN: "bg-ink-faint" };
const METRICS = [{ key: "cpu", label: "CPU", unit: "%", max: 100 }, { key: "memory", label: "Memory", unit: "%", max: 100 }, { key: "network_rx", label: "Network in", unit: "", max: undefined }] as const;
const RANGES = [{ m: 30, l: "30 min" }, { m: 60, l: "1 hour" }, { m: 360, l: "6 hours" }, { m: 1440, l: "24 hours" }];

function ServiceTile({ s }: { s: Service }) {
  return (
    <Link to={`/services/${s.id}`} className="rounded-md border border-line bg-bg p-3 transition hover:border-brand" aria-label={`${s.name}: ${s.status}`}>
      <div className="flex items-center gap-2"><span className={cx("h-2.5 w-2.5 shrink-0 rounded-full", DOT[s.status] ?? "bg-ink-faint")} aria-hidden /><span className="truncate text-sm font-medium">{s.name}</span></div>
      <div className="mt-2 flex justify-between text-xs text-ink-dim"><span>{s.status}</span><span className="tabular-nums">{formatMs(s.last_response_ms)}</span></div>
      <div className="mt-1 flex justify-between text-xs text-ink-faint"><span>24h avail.</span><span className="tabular-nums">{formatPercent(s.availability_24h, 2)}</span></div>
    </Link>
  );
}

function TrendCard() {
  const servers = useServers({ page_size: 100, sort: "name" });
  const [pick, setPick] = useState("");
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("cpu");
  const [minutes, setMinutes] = useState(60);
  const first = servers.data?.items.find((s) => s.prometheus_instance)?.id ?? servers.data?.items[0]?.id ?? "";
  const id = pick || first;
  const range = useServerRange(id, metric, minutes);
  const m = METRICS.find((x) => x.key === metric)!;
  return (
    <Card title="Resource trend" className="lg:col-span-2"
      actions={servers.data && servers.data.items.length > 0 ? <>
        <Select aria-label="Server" value={id} onChange={(e) => setPick(e.target.value)} className="!w-44 !py-1">{servers.data.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
        <div role="tablist" aria-label="Metric" className="flex overflow-hidden rounded-md border border-line">
          {METRICS.map((x) => <button key={x.key} role="tab" aria-selected={metric === x.key} onClick={() => setMetric(x.key)} className={cx("px-2.5 py-1 text-xs", metric === x.key ? "bg-brand/15 text-brand" : "text-ink-dim hover:bg-bg-hover")}>{x.label}</button>)}
        </div>
        <Select aria-label="Range" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} className="!w-24 !py-1">{RANGES.map((r) => <option key={r.m} value={r.m}>{r.l}</option>)}</Select>
      </> : undefined}>
      {!id ? <EmptyState title="No servers yet" hint="Register a server to see its resource trend." action={<Link className="text-brand" to="/servers">Go to Servers</Link>} /> : <TimeSeriesChart data={range.data} unit={m.unit} max={m.max} height={240} />}
    </Card>
  );
}

export default function Overview() {
  const q = useOverview();
  const qc = useQueryClient();
  const services = useServices({ page_size: 100, sort: "name" });
  const summary = useReport<Summary>("summary", 7);
  const incRep = useReport<IncRep>("incidents", 7);
  const tiles = useMemo(() => [...(services.data?.items ?? [])].sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.name.localeCompare(b.name)), [services.data]);
  const refresh = () => { void qc.invalidateQueries(); };

  return (
    <>
      <PageHeader title="Overview" subtitle={q.data ? `Updated ${formatRelative(q.data.generated_at)} · refreshes every 15 s` : "Live state of servers, services, incidents and recovery."}
        actions={<Button onClick={refresh} loading={q.isFetching && !q.isLoading}>Refresh</Button>} />
      <QueryBoundary query={q}>
        {(o) => {
          const p = computePosture(o);
          const h = HERO[p.level];
          const rate = recoverySuccessRate(o.recovery_activity_24h);
          const mttr = summary.data?.mttr_minutes;
          return (
            <div className="space-y-5">
              <section role="status" aria-live="polite" className={cx("flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border px-5 py-4", h.bar)}>
                <span className={cx("h-3.5 w-3.5 rounded-full", h.dot, p.level !== "operational" && "animate-pulse")} aria-hidden />
                <div className="min-w-0 flex-1">
                  <h2 className={cx("text-lg font-semibold", h.text)}>{p.headline}</h2>
                  {p.reasons.length > 0 && <p className="text-sm text-ink-dim">{p.reasons.join(" · ")}</p>}
                </div>
                {p.caveats.map((c) => <Badge key={c} tone="warn">{c}</Badge>)}
              </section>

              <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
                <StatCard label="Active incidents" value={o.incidents.active} tone={o.incidents.critical ? "crit" : o.incidents.active ? "warn" : "ok"} sub={`${o.incidents.critical} critical`} to="/incidents" />
                <StatCard label="Services up" value={`${o.services.up}/${o.services.total}`} tone={o.services.down ? "crit" : o.services.degraded ? "warn" : o.services.total ? "ok" : undefined} sub={`${o.services.down} down · ${o.services.degraded} degraded`} to="/services" />
                <StatCard label="Availability 24h" value={formatPercent(o.services.availability_24h_percent, 2)} sub="all services" />
                <StatCard label="Latency (15 min)" value={formatMs(o.services.avg_latency_ms_15m)} sub="average response" />
                <StatCard label="Servers healthy" value={`${o.servers.healthy}/${o.servers.total}`} tone={o.servers.unhealthy ? "crit" : o.servers.degraded ? "warn" : undefined} sub={`${o.servers.unknown} unknown`} to="/servers" />
                <StatCard label="MTTR (7 days)" value={mttr === null || mttr === undefined ? DASH : formatDuration(mttr * 60)} sub={rate === null ? "no recoveries in 24 h" : `recovery success ${formatPercent(rate, 0)} (24 h)`} />
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <TrendCard />
                <Card title="Fleet utilization (average)">
                  <div className="space-y-4">
                    <Meter label="CPU" value={o.utilization.cpu_percent} />
                    <Meter label="Memory" value={o.utilization.memory_percent} />
                    <Meter label="Disk" value={o.utilization.disk_percent} />
                  </div>
                  {!o.monitoring.prometheus_available && <p className="mt-4 text-xs text-warn">Prometheus is unreachable: values show “no data”, never zero.</p>}
                </Card>
              </div>

              <Card title="Service health" actions={<Link className="text-xs text-brand" to="/services">All services</Link>}>
                <QueryBoundary query={services}>{() => tiles.length === 0 ? <EmptyState title="No services configured" hint="Add a service to start availability checks." /> : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">{tiles.map((s) => <ServiceTile key={s.id} s={s} />)}</div>
                )}</QueryBoundary>
              </Card>

              <div className="grid gap-4 lg:grid-cols-3">
                <Card title="Incidents per day (7 days)"><QueryBoundary query={incRep}>{(r) => <SimpleBars height={180} data={r.per_day.map((d) => ({ name: d.date.slice(5), value: d.count }))} />}</QueryBoundary></Card>
                <Card title="Incidents by severity (7 days)"><QueryBoundary query={summary}>{(s) => <Donut height={180} data={[
                  { name: "Critical", value: s.by_severity.CRITICAL ?? 0, color: "#ef5350" }, { name: "Warning", value: s.by_severity.WARNING ?? 0, color: "#f0a63a" }, { name: "Info", value: s.by_severity.INFO ?? 0, color: "#4f8cff" }]} />}</QueryBoundary></Card>
                <Card title="Recovery activity (24 h)">
                  {Object.keys(o.recovery_activity_24h).length === 0 ? <EmptyState title="No recovery executions" hint="Dry runs are not counted." /> : (
                    <ul className="space-y-2 text-sm">{Object.entries(o.recovery_activity_24h).map(([k, n]) => <li key={k} className="flex justify-between"><span className="text-ink-dim">{k.replaceAll("_", " ").toLowerCase()}</span><span className="tabular-nums">{n}</span></li>)}</ul>
                  )}
                </Card>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card title="Recent incidents" actions={<Link className="text-xs text-brand" to="/incidents">View all</Link>} padded={false}>
                  {o.recent_incidents.length === 0 ? <EmptyState title="No incidents" hint="Nothing has been detected." /> : (
                    <ul className="divide-y divide-line/60">{o.recent_incidents.map((i) => (
                      <li key={i.id}><Link to={`/incidents/${i.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-bg-hover">
                        <div className="min-w-0"><div className="truncate text-sm">{i.title}</div><div className="text-xs text-ink-faint">{formatRelative(i.last_seen_at)}</div></div>
                        <div className="flex shrink-0 gap-2"><SeverityBadge severity={i.severity} /><IncidentStatusBadge status={i.status} /></div>
                      </Link></li>))}</ul>
                  )}
                </Card>
                <Card title="Recent notifications" actions={<Link className="text-xs text-brand" to="/alerts">View all</Link>} padded={false}>
                  {o.recent_alerts.length === 0 ? <EmptyState title="No notifications" /> : (
                    <ul className="divide-y divide-line/60">{o.recent_alerts.map((n) => (
                      <li key={n.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                        <div className="min-w-0"><div className="truncate text-sm">{n.title}</div><div className="text-xs text-ink-faint">{formatRelative(n.created_at)}</div></div>
                        <Badge tone={n.status === "SENT" ? "ok" : n.status === "FAILED" ? "crit" : "neutral"}>{n.status}</Badge>
                      </li>))}</ul>
                  )}
                </Card>
              </div>
            </div>
          );
        }}
      </QueryBoundary>
    </>
  );
}
