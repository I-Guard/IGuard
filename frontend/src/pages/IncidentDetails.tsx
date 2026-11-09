import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useParams } from "react-router-dom";
import { z } from "zod";
import { IncidentStatusBadge, SeverityBadge } from "../components/badges";
import { QueryBoundary, errorMessage } from "../components/feedback";
import { Modal } from "../components/Modal";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, KeyValue, PageHeader, Select, Textarea } from "../components/ui";
import { useAction, useAssignable, useIncident, useRecoveryActions, useTimeline } from "../hooks/queries";
import { api } from "../services/api";
import type { IncidentStatus } from "../types/api";
import { DASH, formatDateTime, formatRelative } from "../utils/format";
import { useAuth } from "../contexts/AuthContext";

const resolveSchema = z.object({ resolution_summary: z.string().trim().min(3, "Describe the resolution (min 3 chars)").max(4000), root_cause: z.string().max(4000).optional() });
type ResolveForm = z.infer<typeof resolveSchema>;

const NEXT: Partial<Record<IncidentStatus, IncidentStatus[]>> = { DETECTED: ["INVESTIGATING"], ACKNOWLEDGED: ["INVESTIGATING"], INVESTIGATING: ["RECOVERING"], RECOVERING: ["INVESTIGATING"] };

export default function IncidentDetails() {
  const { id = "" } = useParams();
  const toast = useToast();
  const { hasRole } = useAuth();
  const inc = useIncident(id);
  const timeline = useTimeline(id);
  const actions = useRecoveryActions();
  const assignable = useAssignable(hasRole("OPERATOR"));
  const [resolving, setResolving] = useState(false);
  const [assignee, setAssignee] = useState("");
  const inv = ["incident", "incidents", "timeline", "overview"];
  const ack = useAction(() => api.post(`/incidents/${id}/acknowledge`, {}), inv);
  const status = useAction((s: IncidentStatus) => api.post(`/incidents/${id}/status`, { status: s }), inv);
  const assign = useAction((uid: string) => api.post(`/incidents/${id}/assign`, { assignee_id: uid }), inv);
  const resolve = useAction((v: ResolveForm) => api.post(`/incidents/${id}/resolve`, { resolution_summary: v.resolution_summary, root_cause: v.root_cause || null }), inv);
  const { register, handleSubmit, reset, formState: { errors } } = useForm<ResolveForm>({ resolver: zodResolver(resolveSchema) });
  const onErr = (e: unknown) => toast.error(errorMessage(e));

  return (
    <QueryBoundary query={inc}>
      {(i) => {
        const open = i.status !== "RESOLVED";
        const relevant = (actions.data ?? []).filter((a) => a.service_id === i.service_id && a.service_id !== null);
        return (
          <>
            <PageHeader title={i.title} subtitle={<span className="flex flex-wrap items-center gap-2"><SeverityBadge severity={i.severity} /><IncidentStatusBadge status={i.status} />{i.is_flapping && <Badge tone="warn">flapping</Badge>}{i.escalation_level > 0 && <Badge tone="crit">escalated L{i.escalation_level}</Badge>}<span>first seen {formatRelative(i.first_seen_at)}</span></span>}
              actions={open ? <Can role="OPERATOR">
                {i.status === "DETECTED" && <Button loading={ack.isPending} onClick={() => ack.mutate(undefined, { onSuccess: () => toast.success("Acknowledged"), onError: onErr })}>Acknowledge</Button>}
                {(NEXT[i.status] ?? []).map((s) => <Button key={s} loading={status.isPending} onClick={() => status.mutate(s, { onSuccess: () => toast.success(`Status: ${s}`), onError: onErr })}>Mark {s.toLowerCase()}</Button>)}
                <Button variant="primary" onClick={() => { reset(); setResolving(true); }}>Resolve</Button>
              </Can> : undefined} />
            {i.description && <p className="mb-4 text-sm text-ink-dim">{i.description}</p>}
            <div className="grid gap-4 lg:grid-cols-3">
              <Card title="Details">
                <KeyValue items={[
                  ["Category", i.category], ["Source", i.source], ["Server", i.server_name ?? DASH], ["Service", i.service_name ?? DASH],
                  ["Occurrences", String(i.occurrences)], ["Flap count", String(i.flap_count)], ["Last seen", formatDateTime(i.last_seen_at)],
                  ["Acknowledged by", i.acknowledged_by?.username ?? DASH], ["Assigned to", i.assigned_to?.username ?? DASH],
                  ["Resolved", formatDateTime(i.resolved_at)], ["Root cause", i.root_cause ?? DASH], ["Resolution", i.resolution_summary ?? DASH],
                ]} />
              </Card>
              <Card title="Timeline" className="lg:col-span-2" padded={false}>
                <QueryBoundary query={timeline}>{(ev) => ev.length === 0 ? <p className="p-4 text-sm text-ink-dim">No events.</p> : (
                  <ol className="divide-y divide-line/60">{ev.map((e) => (
                    <li key={e.id} className="px-4 py-2.5"><div className="flex items-center justify-between gap-3"><Badge>{e.event_type.replaceAll("_", " ")}</Badge><time className="text-xs text-ink-faint" dateTime={e.created_at}>{formatDateTime(e.created_at)}</time></div>
                      <p className="mt-1 text-sm">{e.message}</p>{e.actor_name && <p className="text-xs text-ink-faint">by {e.actor_name}</p>}</li>))}</ol>)}</QueryBoundary>
              </Card>
            </div>
            <Can role="OPERATOR">
              {open && (
                <Card className="mt-4" title="Assign">
                  <div className="flex max-w-md gap-2"><Select aria-label="Assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">Select a user…</option>{assignable.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}</Select>
                    <Button disabled={!assignee} loading={assign.isPending} onClick={() => assign.mutate(assignee, { onSuccess: () => toast.success("Assigned"), onError: onErr })}>Assign</Button></div>
                </Card>
              )}
            </Can>
            <Card className="mt-4" title="Recovery actions for this service">
              {relevant.length === 0 ? <p className="text-sm text-ink-dim">No recovery action is registered for this incident’s service.</p> : (
                <ul className="space-y-2 text-sm">{relevant.map((a) => <li key={a.id} className="flex items-center justify-between"><span>{a.name}{a.sensitive && <> <Badge tone="warn">sensitive</Badge></>}</span><Link className="text-brand" to={`/recovery?action=${a.id}&incident=${i.id}`}>Open in Recovery</Link></li>)}</ul>
              )}
            </Card>
            {i.related.length > 0 && (
              <Card className="mt-4" title="Correlated incidents" padded={false}>
                <ul className="divide-y divide-line/60">{i.related.map((r) => <li key={r.id}><Link to={`/incidents/${r.id}`} className="flex items-center justify-between px-4 py-2.5 hover:bg-bg-hover"><span className="text-sm">{r.title}</span><IncidentStatusBadge status={r.status} /></Link></li>)}</ul>
              </Card>
            )}
            <Modal open={resolving} title="Resolve incident" onClose={() => setResolving(false)}>
              <form noValidate className="space-y-3" onSubmit={handleSubmit((v) => resolve.mutate(v, { onSuccess: () => { toast.success("Incident resolved"); setResolving(false); }, onError: onErr }))}>
                <Field label="Resolution summary" htmlFor="res-sum" error={errors.resolution_summary?.message}><Textarea id="res-sum" rows={3} {...register("resolution_summary")} /></Field>
                <Field label="Root cause (optional)" htmlFor="res-rc" error={errors.root_cause?.message}><Textarea id="res-rc" rows={2} {...register("root_cause")} /></Field>
                <div className="flex justify-end gap-2"><Button type="button" onClick={() => setResolving(false)}>Cancel</Button><Button type="submit" variant="primary" loading={resolve.isPending}>Resolve</Button></div>
              </form>
            </Modal>
          </>
        );
      }}
    </QueryBoundary>
  );
}
