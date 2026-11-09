import { useNavigate } from "react-router-dom";
import { IncidentStatusBadge, SeverityBadge } from "../components/badges";
import { DataTable, Pagination } from "../components/DataTable";
import { QueryBoundary } from "../components/feedback";
import { Badge, Card, Input, PageHeader, Select } from "../components/ui";
import { useIncidents } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import { formatRelative } from "../utils/format";

export default function Incidents() {
  const nav = useNavigate();
  const t = useTableParams({ sort: "-created_at" });
  const q = useIncidents(t.query);
  return (
    <>
      <PageHeader title="Incidents" subtitle="Deduplicated incidents detected from checks and alerts." />
      <Card padded={false}>
        <div className="flex flex-wrap gap-3 border-b border-line p-3">
          <Input aria-label="Search incidents" placeholder="Search title…" className="max-w-xs" value={t.filters.search ?? ""} onChange={(e) => t.setFilter("search", e.target.value)} />
          <Select aria-label="Status filter" className="max-w-[12rem]" value={t.filters.status ?? ""} onChange={(e) => t.setFilter("status", e.target.value)}>
            <option value="">All statuses</option>{["DETECTED", "ACKNOWLEDGED", "INVESTIGATING", "RECOVERING", "RESOLVED"].map((s) => <option key={s}>{s}</option>)}
          </Select>
          <Select aria-label="Severity filter" className="max-w-[10rem]" value={t.filters.severity ?? ""} onChange={(e) => t.setFilter("severity", e.target.value)}>
            <option value="">All severities</option>{["CRITICAL", "WARNING", "INFO"].map((s) => <option key={s}>{s}</option>)}
          </Select>
        </div>
        <QueryBoundary query={q}>
          {(p) => (
            <>
              <DataTable rows={p.items} rowKey={(i) => i.id} sort={t.sort} onSort={t.setSort} onRowClick={(i) => nav(`/incidents/${i.id}`)}
                empty={{ title: "No incidents match", hint: "Nothing detected, or the filters exclude everything." }}
                columns={[
                  { key: "sev", header: "Severity", sortKey: "severity", render: (i) => <SeverityBadge severity={i.severity} /> },
                  { key: "title", header: "Title", sortKey: "title", render: (i) => <div><span className="font-medium">{i.title}</span>{i.is_flapping && <> <Badge tone="warn">flapping</Badge></>}</div> },
                  { key: "st", header: "Status", sortKey: "status", render: (i) => <IncidentStatusBadge status={i.status} /> },
                  { key: "target", header: "Target", render: (i) => i.service_name ?? i.server_name ?? "—" },
                  { key: "occ", header: "Occurrences", sortKey: "occurrences", render: (i) => i.occurrences },
                  { key: "esc", header: "Esc.", render: (i) => (i.escalation_level ? `L${i.escalation_level}` : "—") },
                  { key: "seen", header: "Last seen", render: (i) => formatRelative(i.last_seen_at) },
                  { key: "created", header: "Opened", sortKey: "created_at", render: (i) => formatRelative(i.created_at) },
                ]} />
              <Pagination page={p} onPage={t.setPage} />
            </>
          )}
        </QueryBoundary>
      </Card>
    </>
  );
}
