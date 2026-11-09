import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ExecutionBadge } from "../components/badges";
import { QueryBoundary, errorMessage, NoticeBanner } from "../components/feedback";
import { Modal } from "../components/Modal";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, Input, PageHeader } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { useAction, useRecoveryActions } from "../hooks/queries";
import { api } from "../services/api";
import type { RecoveryAction, RecoveryExecution } from "../types/api";
import { formatDateTime, formatDuration, formatRelative } from "../utils/format";

function newKey(): string { return `ui-${crypto.randomUUID()}`; }

function ResultBox({ r }: { r: RecoveryExecution }) {
  return (
    <div className="mt-3 rounded-md border border-line bg-bg p-3 text-sm" role="status">
      <div className="flex items-center gap-2"><ExecutionBadge status={r.status} />{r.dry_run && <Badge tone="info">dry run</Badge>}{r.simulated && <Badge tone="warn">simulated</Badge>}</div>
      {r.output && <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-ink-dim">{r.output}</pre>}
      {r.error && <p className="mt-2 text-xs text-crit">{r.error}</p>}
    </div>
  );
}

function ActionCard({ a, incidentId }: { a: RecoveryAction; incidentId: string | null }) {
  const toast = useToast();
  const { hasRole } = useAuth();
  const [last, setLast] = useState<RecoveryExecution | null>(null);
  const [confirming, setConfirming] = useState<boolean>(false);
  const [typed, setTyped] = useState("");
  const inv = ["recovery-actions", "recovery-history", "incidents", "incident", "timeline"];
  const dry = useAction(() => api.post<RecoveryExecution>(`/recovery/actions/${a.id}/dry-run`, { incident_id: incidentId }), inv);
  const exec = useAction((confirm: boolean) => api.post<RecoveryExecution>(`/recovery/actions/${a.id}/execute`, { incident_id: incidentId, confirm }, { headers: { "Idempotency-Key": newKey() } }), inv);
  const blockedByRole = !hasRole(a.min_role);
  const blocked = !a.enabled || a.circuit_open || a.cooldown_remaining_seconds > 0 || blockedByRole;
  const reason = !a.enabled ? "Disabled" : a.circuit_open ? "Circuit breaker open" : a.cooldown_remaining_seconds > 0 ? `Cooldown ${formatDuration(a.cooldown_remaining_seconds)}` : blockedByRole ? `Requires ${a.min_role}` : null;

  const runExec = (confirm: boolean) => exec.mutate(confirm, { onSuccess: (r) => { setLast(r); setConfirming(false); setTyped(""); if (r.status === "SUCCEEDED") toast.success("Recovery succeeded"); else toast.error(`Recovery ${r.status.toLowerCase().replaceAll("_", " ")}`); }, onError: (e) => { toast.error(errorMessage(e)); setConfirming(false); } });

  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{a.name}{a.sensitive && <Badge tone="warn">sensitive</Badge>}{a.auto_trigger && <Badge tone="info">auto</Badge>}{a.circuit_open && <Badge tone="crit">breaker open</Badge>}</span>}>
      <p className="text-sm text-ink-dim">{a.description}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink-faint">
        <dt>Type</dt><dd className="text-ink">{a.action_type}</dd><dt>Target</dt><dd className="text-ink">{a.target}</dd>
        <dt>Cooldown</dt><dd className="text-ink">{formatDuration(a.cooldown_seconds)}</dd><dt>Min role</dt><dd className="text-ink">{a.min_role}</dd>
        <dt>Last run</dt><dd className="text-ink">{a.last_execution_at ? formatRelative(a.last_execution_at) : "never"}{a.last_status && <> · {a.last_status}</>}</dd>
      </dl>
      {reason && <p className="mt-2 text-xs text-warn">Unavailable: {reason}</p>}
      <Can role="OPERATOR">
        <div className="mt-3 flex gap-2">
          <Button loading={dry.isPending} disabled={!a.enabled || a.circuit_open || blockedByRole} onClick={() => dry.mutate(undefined, { onSuccess: (r) => { setLast(r); toast.info("Dry run complete"); }, onError: (e) => toast.error(errorMessage(e)) })}>Dry run</Button>
          <Button variant="primary" disabled={blocked} loading={exec.isPending} onClick={() => (a.sensitive ? setConfirming(true) : runExec(false))}>Execute</Button>
        </div>
      </Can>
      {last && <ResultBox r={last} />}
      <Modal open={confirming} title={`Confirm sensitive action: ${a.name}`} onClose={() => setConfirming(false)}
        footer={<><Button onClick={() => setConfirming(false)}>Cancel</Button><Button variant="danger" disabled={typed !== a.key} loading={exec.isPending} onClick={() => runExec(true)}>Execute</Button></>}>
        <p className="text-sm text-ink-dim">This action is classified sensitive and requires explicit confirmation. A successful dry run within the last 15 minutes is required.</p>
        <div className="mt-3"><Field label={`Type “${a.key}” to confirm`} htmlFor={`confirm-${a.id}`}><Input id={`confirm-${a.id}`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></Field></div>
      </Modal>
    </Card>
  );
}

export default function Recovery() {
  const q = useRecoveryActions();
  const [sp] = useSearchParams();
  const incidentId = sp.get("incident");
  const sorted = useMemo(() => [...(q.data ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [q.data]);
  return (
    <>
      <PageHeader title="Recovery operations" subtitle="Allowlisted actions only. No arbitrary commands; every run is audited." />
      <NoticeBanner tone="info">Dry runs validate the action without changing anything. Real executions honor cooldowns, rate limits and circuit breakers. Database and other critical targets are never auto-restarted.</NoticeBanner>
      {incidentId && <p className="mb-3 text-sm text-ink-dim">Linked to incident <code>{incidentId.slice(0, 8)}</code>.</p>}
      <QueryBoundary query={q}>
        {() => sorted.length === 0 ? <Card><p className="text-sm text-ink-dim">No recovery actions are registered. Add a policy file and restart the backend.</p></Card> : (
          <div className="grid gap-4 lg:grid-cols-2">{sorted.map((a) => <ActionCard key={a.id} a={a} incidentId={incidentId} />)}</div>
        )}
      </QueryBoundary>
      <p className="mt-4 text-xs text-ink-faint">Last refreshed {formatDateTime(new Date(q.dataUpdatedAt).toISOString())}</p>
    </>
  );
}
