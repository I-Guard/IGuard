import { Link } from "react-router-dom";
import { Meter } from "../components/charts";
import { HealthBadge } from "../components/badges";
import { QueryBoundary } from "../components/feedback";
import { Card, PageHeader, StatCard } from "../components/ui";
import { useOverview, useServerMetrics, useServers } from "../hooks/queries";
import type { Server } from "../types/api";

function ServerTile({ s }: { s: Server }) {
  const m = useServerMetrics(s.id, !!s.prometheus_instance);
  const d = m.data?.metrics;
  return (
    <Link to={`/servers/${s.id}`} className="card block p-4 hover:ring-1 hover:ring-brand">
      <div className="mb-3 flex items-center justify-between"><span className="font-medium">{s.name}</span><HealthBadge health={s.health} /></div>
      <div className="space-y-3">
        <Meter label="CPU" value={d?.cpu_usage_percent ?? null} />
        <Meter label="Memory" value={d?.memory_usage_percent ?? null} />
        <Meter label="Disk" value={d?.disk_usage_percent ?? null} />
      </div>
    </Link>
  );
}

export default function Infrastructure() {
  const o = useOverview();
  const servers = useServers({ page_size: 100, sort: "name" });
  return (
    <>
      <PageHeader title="Infrastructure" subtitle="Resource utilization across all monitored hosts." />
      {o.data && (
        <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Healthy" value={o.data.servers.healthy} tone="ok" />
          <StatCard label="Degraded" value={o.data.servers.degraded} tone={o.data.servers.degraded ? "warn" : undefined} />
          <StatCard label="Unhealthy" value={o.data.servers.unhealthy} tone={o.data.servers.unhealthy ? "crit" : undefined} />
          <StatCard label="Unknown" value={o.data.servers.unknown} />
        </div>
      )}
      <QueryBoundary query={servers}>
        {(p) => p.items.length === 0 ? <Card><p className="text-sm text-ink-dim">No servers registered yet.</p></Card> : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{p.items.map((s) => <ServerTile key={s.id} s={s} />)}</div>
        )}
      </QueryBoundary>
    </>
  );
}
