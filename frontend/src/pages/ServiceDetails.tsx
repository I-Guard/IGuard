import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { SimpleBars } from "../components/charts";
import { ServiceStatusBadge } from "../components/badges";
import { DataTable } from "../components/DataTable";
import { QueryBoundary, errorMessage } from "../components/feedback";
import { ConfirmDialog, Modal } from "../components/Modal";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, KeyValue, PageHeader, StatCard } from "../components/ui";
import { checkServiceNow, useAction, useService, useServiceAvailability, useServiceChecks } from "../hooks/queries";
import { api } from "../services/api";
import { DASH, formatDateTime, formatMs, formatPercent, formatRelative } from "../utils/format";
import { ServiceForm } from "./Services";

export default function ServiceDetails() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const svc = useService(id);
  const checks = useServiceChecks(id);
  const avail = useServiceAvailability(id);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const run = useAction(() => checkServiceNow(id), ["service", "service-checks", "services", "service-avail"]);
  const del = useAction(() => api.del(`/services/${id}`), ["services", "overview"]);

  return (
    <QueryBoundary query={svc}>
      {(s) => (
        <>
          <PageHeader title={s.name} subtitle={<span className="flex flex-wrap items-center gap-2"><ServiceStatusBadge status={s.status} /><Badge>{s.check_type}</Badge>{!s.enabled && <Badge tone="warn">disabled</Badge>}<span>{s.url ?? `${s.host}:${s.port}`}</span></span>}
            actions={<>
              <Can role="OPERATOR"><Button loading={run.isPending} onClick={() => run.mutate(undefined, { onSuccess: (r) => (r.success ? toast.success(`Check passed (${formatMs(r.response_time_ms)})`) : toast.error(`Check failed: ${r.error ?? "unexpected status"}`)), onError: (e) => toast.error(errorMessage(e)) })}>Run check now</Button></Can>
              <Can role="ADMIN"><Button onClick={() => setEditing(true)}>Edit</Button><Button variant="danger" onClick={() => setDeleting(true)}>Delete</Button></Can>
            </>} />
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Availability 1h" value={formatPercent(avail.data?.["1h"] ?? null, 2)} />
            <StatCard label="Availability 24h" value={formatPercent(avail.data?.["24h"] ?? null, 2)} />
            <StatCard label="Availability 7d" value={formatPercent(avail.data?.["7d"] ?? null, 2)} />
            <StatCard label="Last response" value={formatMs(s.last_response_ms)} sub={s.last_checked_at ? `checked ${formatRelative(s.last_checked_at)}` : "never checked"} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Configuration" className="lg:col-span-1">
              <KeyValue items={[
                ["Server", s.server_name ?? DASH], ["Interval", `${s.interval_seconds}s`], ["Timeout", `${s.timeout_seconds}s`], ["Failures to alert", String(s.retry_threshold)],
                ["Latency threshold", formatMs(s.latency_threshold_ms)], ["Expected codes", s.expected_status_codes.join(", ")], ["Container", s.container_name ?? DASH],
                ["Consecutive failures", String(s.consecutive_failures)], ["Last status code", s.last_status_code === null ? DASH : String(s.last_status_code)], ["Last error", s.last_error ?? DASH],
                ["Status since", formatDateTime(s.status_since)],
              ]} />
            </Card>
            <Card title="Response time (recent checks, ms)" className="lg:col-span-2">
              <QueryBoundary query={checks}>
                {(cs) => <SimpleBars height={220} data={cs.filter((c) => c.response_time_ms !== null).slice(0, 40).reverse().map((c) => ({ name: new Date(c.checked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), value: Math.round(c.response_time_ms ?? 0) }))} />}
              </QueryBoundary>
            </Card>
          </div>
          <Card className="mt-4" title="Recent checks" padded={false}>
            <QueryBoundary query={checks}>
              {(cs) => <DataTable rows={cs.slice(0, 50)} rowKey={(c) => String(c.id)} empty={{ title: "No checks recorded yet" }} columns={[
                { key: "t", header: "Time", render: (c) => formatDateTime(c.checked_at) },
                { key: "r", header: "Result", render: (c) => <Badge tone={c.success ? "ok" : "crit"}>{c.success ? "OK" : "FAIL"}</Badge> },
                { key: "c", header: "Status code", render: (c) => c.status_code ?? DASH },
                { key: "l", header: "Latency", render: (c) => formatMs(c.response_time_ms) },
                { key: "e", header: "Error", render: (c) => c.error ?? DASH },
              ]} />}
            </QueryBoundary>
          </Card>
          <Modal open={editing} title="Edit service" wide onClose={() => setEditing(false)}><ServiceForm initial={s} onDone={() => setEditing(false)} onCancel={() => setEditing(false)} /></Modal>
          <ConfirmDialog open={deleting} danger title="Delete service" confirmLabel="Delete" loading={del.isPending}
            message={<>Delete <strong>{s.name}</strong> and its check history? Recovery actions targeting it are detached.</>} onCancel={() => setDeleting(false)}
            onConfirm={() => del.mutate(undefined, { onSuccess: () => { toast.success("Service deleted"); nav("/services"); }, onError: (e) => { toast.error(errorMessage(e)); setDeleting(false); } })} />
        </>
      )}
    </QueryBoundary>
  );
}
