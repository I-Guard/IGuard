import { useState } from "react";
import { SimpleBars } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { QueryBoundary } from "../components/feedback";
import { Card, PageHeader, Select, StatCard } from "../components/ui";
import { useReport } from "../hooks/queries";
import { DASH, formatDuration, formatMs, formatPercent } from "../utils/format";

interface Summary { incidents_total: number; incidents_open: number; mttr_minutes: number | null; by_severity: Record<string, number>; by_category: Record<string, number>; recoveries: Record<string, number>; average_availability_percent: number | null }
interface Avail { items: { service_id: string; service: string; status: string; availability_percent: number | null; last_response_ms: number | null }[] }
interface IncRep { per_day: { date: string; count: number }[]; top_recurring: { title: string; occurrences: number }[]; flapping: number; by_status: Record<string, number> }
interface RecRep { total: number; succeeded: number; success_rate_percent: number | null; automatic: number; manual: number; by_action: { action: string; total: number; succeeded: number; failed: number; avg_duration_ms: number | null }[] }
const bars = (o: Record<string, number>) => Object.entries(o).map(([name, value]) => ({ name, value }));

export default function Reports() {
  const [days, setDays] = useState(7);
  const sum = useReport<Summary>("summary", days);
  const av = useReport<Avail>("availability", days);
  const inc = useReport<IncRep>("incidents", days);
  const rec = useReport<RecRep>("recovery", days);
  return (
    <>
      <PageHeader title="Reports" subtitle="Computed from recorded incidents, checks and recovery runs." actions={<Select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[1, 7, 30, 90].map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}</Select>} />
      <QueryBoundary query={sum}>
        {(s) => (
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Incidents" value={s.incidents_total} sub={`${s.incidents_open} open`} />
            <StatCard label="MTTR" value={s.mttr_minutes === null ? DASH : formatDuration(s.mttr_minutes * 60)} sub="mean time to resolve" />
            <StatCard label="Avg availability" value={formatPercent(s.average_availability_percent, 2)} />
            <StatCard label="Recoveries" value={Object.values(s.recoveries).reduce((a, b) => a + b, 0)} />
          </div>
        )}
      </QueryBoundary>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Incidents by severity"><QueryBoundary query={sum}>{(s) => <SimpleBars data={bars(s.by_severity)} />}</QueryBoundary></Card>
        <Card title="Incidents per day"><QueryBoundary query={inc}>{(r) => <SimpleBars data={r.per_day.map((d) => ({ name: d.date.slice(5), value: d.count }))} />}</QueryBoundary></Card>
        <Card title="Service availability" padded={false}><QueryBoundary query={av}>{(r) => <DataTable rows={r.items} rowKey={(x) => x.service_id} empty={{ title: "No services" }} columns={[
          { key: "s", header: "Service", render: (x) => x.service }, { key: "a", header: "Availability", render: (x) => formatPercent(x.availability_percent, 2) }, { key: "l", header: "Last latency", render: (x) => formatMs(x.last_response_ms) }]} />}</QueryBoundary></Card>
        <Card title="Top recurring incidents" padded={false}><QueryBoundary query={inc}>{(r) => <DataTable rows={r.top_recurring} rowKey={(x) => x.title} empty={{ title: "None" }} columns={[{ key: "t", header: "Title", render: (x) => x.title }, { key: "o", header: "Occurrences", render: (x) => x.occurrences }]} />}</QueryBoundary></Card>
        <Card title="Recovery by action" className="lg:col-span-2" padded={false}><QueryBoundary query={rec}>{(r) => <DataTable rows={r.by_action} rowKey={(x) => x.action} empty={{ title: "No recovery executions in this period" }} columns={[
          { key: "a", header: "Action", render: (x) => x.action }, { key: "t", header: "Total", render: (x) => x.total }, { key: "s", header: "Succeeded", render: (x) => x.succeeded },
          { key: "f", header: "Failed", render: (x) => x.failed }, { key: "d", header: "Avg duration", render: (x) => formatMs(x.avg_duration_ms) }]} />}</QueryBoundary></Card>
      </div>
    </>
  );
}
