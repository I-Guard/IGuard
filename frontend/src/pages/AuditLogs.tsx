import { useState } from "react";
import { DataTable, Pagination } from "../components/DataTable";
import { Modal } from "../components/Modal";
import { QueryBoundary } from "../components/feedback";
import { Badge, Card, Input, PageHeader, Select } from "../components/ui";
import { useAudit } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import type { AuditLog } from "../types/api";
import { DASH, formatDateTime } from "../utils/format";

export default function AuditLogs() {
  const t = useTableParams({ sort: "-created_at" });
  const q = useAudit(t.query);
  const [sel, setSel] = useState<AuditLog | null>(null);
  return (
    <>
      <PageHeader title="Audit logs" subtitle="Security-relevant actions. Secrets are never recorded." />
      <Card padded={false}>
        <div className="flex flex-wrap gap-3 border-b border-line p-3">
          <Input aria-label="Actor" placeholder="Actor" className="max-w-[12rem]" value={t.filters.actor ?? ""} onChange={(e) => t.setFilter("actor", e.target.value)} />
          <Input aria-label="Action" placeholder="Action (e.g. auth.login)" className="max-w-[14rem]" value={t.filters.action ?? ""} onChange={(e) => t.setFilter("action", e.target.value)} />
          <Select aria-label="Outcome" className="max-w-[10rem]" value={t.filters.outcome ?? ""} onChange={(e) => t.setFilter("outcome", e.target.value)}><option value="">All outcomes</option>{["SUCCESS", "FAILURE", "REJECTED", "LOCKED", "RATE_LIMITED", "DISABLED", "REVOKED", "STARTED"].map((o) => <option key={o} value={o}>{o}</option>)}</Select>
        </div>
        <QueryBoundary query={q}>
          {(p) => (<>
            <DataTable rows={p.items} rowKey={(a) => a.id} sort={t.sort} onSort={t.setSort} onRowClick={setSel} empty={{ title: "No audit entries" }} columns={[
              { key: "t", header: "Time", sortKey: "created_at", render: (a) => formatDateTime(a.created_at) }, { key: "a", header: "Actor", render: (a) => a.actor_name },
              { key: "ac", header: "Action", render: (a) => <code className="text-xs">{a.action}</code> }, { key: "r", header: "Resource", render: (a) => `${a.resource_type}${a.resource_id ? ` ${a.resource_id.slice(0, 8)}` : ""}` },
              { key: "o", header: "Outcome", render: (a) => <Badge tone={a.outcome === "SUCCESS" ? "ok" : a.outcome === "STARTED" ? "info" : "crit"}>{a.outcome}</Badge> }, { key: "ip", header: "IP", render: (a) => a.ip_address ?? DASH },
            ]} />
            <Pagination page={p} onPage={t.setPage} />
          </>)}
        </QueryBoundary>
      </Card>
      <Modal open={!!sel} title="Audit entry" onClose={() => setSel(null)} wide>
        {sel && <pre className="max-h-96 overflow-auto rounded bg-bg p-3 text-xs">{JSON.stringify(sel, null, 2)}</pre>}
      </Modal>
    </>
  );
}
