import { ExecutionBadge } from "../components/badges";
import { DataTable, Pagination } from "../components/DataTable";
import { QueryBoundary } from "../components/feedback";
import { Badge, Card, PageHeader, Select } from "../components/ui";
import { useRecoveryHistory } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import { DASH, formatDateTime, formatMs } from "../utils/format";

export default function RecoveryHistory() {
  const t = useTableParams({ sort: "-created_at" });
  const q = useRecoveryHistory(t.query);
  return (
    <>
      <PageHeader title="Recovery history" subtitle="Every dry run and execution, manual or automatic." />
      <Card padded={false}>
        <div className="flex gap-3 border-b border-line p-3">
          <Select aria-label="Status filter" className="max-w-[14rem]" value={t.filters.status ?? ""} onChange={(e) => t.setFilter("status", e.target.value)}>
            <option value="">All statuses</option>{["DRY_RUN_OK", "RUNNING", "SUCCEEDED", "FAILED", "VERIFICATION_FAILED", "REJECTED"].map((s) => <option key={s}>{s}</option>)}
          </Select>
        </div>
        <QueryBoundary query={q}>
          {(p) => (
            <>
              <DataTable rows={p.items} rowKey={(e) => e.id} empty={{ title: "No recovery executions yet" }} sort={t.sort} onSort={t.setSort}
                columns={[
                  { key: "t", header: "Time", sortKey: "created_at", render: (e) => formatDateTime(e.created_at) },
                  { key: "a", header: "Action", render: (e) => e.action_name ?? e.action_key ?? DASH },
                  { key: "s", header: "Status", render: (e) => <span className="flex gap-1"><ExecutionBadge status={e.status} />{e.dry_run && <Badge tone="info">dry</Badge>}{e.simulated && <Badge tone="warn">sim</Badge>}</span> },
                  { key: "tr", header: "Trigger", render: (e) => e.trigger },
                  { key: "by", header: "By", render: (e) => e.requested_by_name ?? (e.trigger === "AUTOMATIC" ? "system" : DASH) },
                  { key: "v", header: "Verified", render: (e) => (e.verification_passed === null ? DASH : e.verification_passed ? "yes" : "no") },
                  { key: "d", header: "Duration", render: (e) => formatMs(e.duration_ms) },
                  { key: "m", header: "Detail", className: "max-w-xs", render: (e) => <span className="line-clamp-2 break-words text-xs text-ink-dim">{e.error ?? e.output ?? DASH}</span> },
                ]} />
              <Pagination page={p} onPage={t.setPage} />
            </>
          )}
        </QueryBoundary>
      </Card>
    </>
  );
}
