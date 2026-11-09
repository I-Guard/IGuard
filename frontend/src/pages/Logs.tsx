import { useState } from "react";
import { QueryBoundary, NoticeBanner } from "../components/feedback";
import { Badge, Button, Card, Input, PageHeader, Select } from "../components/ui";
import { useLogs } from "../hooks/queries";
import { formatDateTime } from "../utils/format";

const LEVELS = ["", "debug", "info", "warning", "error", "critical"];
const tone = (l?: string) => (l === "error" || l === "critical" ? "crit" : l === "warning" ? "warn" : "neutral");

export default function Logs() {
  const [f, setF] = useState({ service: "", container: "", level: "", q: "", regex: false, minutes: 60, limit: 100 });
  const [applied, setApplied] = useState(() => ({ ...f, since: new Date(Date.now() - f.minutes * 60_000).toISOString() }));
  const params: Record<string, unknown> = { service: applied.service || undefined, container: applied.container || undefined, level: applied.level || undefined, since: applied.since, limit: applied.limit, q: applied.q || undefined, regex: applied.q && applied.regex ? true : undefined };
  const q = useLogs(params);
  return (
    <>
      <PageHeader title="Logs explorer" subtitle="Centralized logs from Loki. Filters use allowlisted labels only." />
      <form className="card mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-6" onSubmit={(e) => { e.preventDefault(); setApplied({ ...f, since: new Date(Date.now() - f.minutes * 60_000).toISOString() }); }} aria-label="Log filters">
        <Input aria-label="Service" placeholder="Service" value={f.service} onChange={(e) => setF({ ...f, service: e.target.value })} />
        <Input aria-label="Container" placeholder="Container" value={f.container} onChange={(e) => setF({ ...f, container: e.target.value })} />
        <Select aria-label="Level" value={f.level} onChange={(e) => setF({ ...f, level: e.target.value })}>{LEVELS.map((l) => <option key={l} value={l}>{l || "All levels"}</option>)}</Select>
        <Select aria-label="Time range" value={f.minutes} onChange={(e) => setF({ ...f, minutes: Number(e.target.value) })}>{[[15, "15 minutes"], [60, "1 hour"], [360, "6 hours"], [1440, "24 hours"]].map(([m, l]) => <option key={m} value={m}>{l}</option>)}</Select>
        <Input aria-label="Search text" placeholder="Search text…" className="lg:col-span-2" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <label className="flex items-center gap-2 text-sm text-ink-dim"><input type="checkbox" checked={f.regex} onChange={(e) => setF({ ...f, regex: e.target.checked })} /> Regex</label>
        <Select aria-label="Limit" value={f.limit} onChange={(e) => setF({ ...f, limit: Number(e.target.value) })}>{[50, 100, 500, 1000].map((n) => <option key={n} value={n}>{n} lines</option>)}</Select>
        <Button type="submit" variant="primary">Search</Button>
      </form>
      <Card padded={false}>
        <QueryBoundary query={q}>
          {(rows) => rows.length === 0 ? <p className="p-6 text-sm text-ink-dim">No log lines match these filters.</p> : (
            <ul className="divide-y divide-line/60 font-mono text-xs" aria-label="Log lines">
              {rows.map((r, i) => (
                <li key={`${r.timestamp}-${i}`} className="flex gap-3 px-3 py-1.5">
                  <time className="shrink-0 text-ink-faint" dateTime={r.timestamp}>{formatDateTime(r.timestamp)}</time>
                  <span className="shrink-0">{(r.fields.level as string | undefined) && <Badge tone={tone(String(r.fields.level))}>{String(r.fields.level)}</Badge>}</span>
                  <span className="shrink-0 text-info">{r.labels.service ?? r.labels.container ?? ""}</span>
                  <span className="min-w-0 break-all text-ink">{String(r.fields.message ?? r.line)}</span>
                </li>
              ))}
            </ul>
          )}
        </QueryBoundary>
      </Card>
      <NoticeBanner tone="info">Sensitive values (tokens, passwords, authorization headers) are redacted before logs are shipped.</NoticeBanner>
    </>
  );
}
