import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { SeverityBadge } from "../components/badges";
import { DataTable, Pagination } from "../components/DataTable";
import { QueryBoundary, errorMessage, NoticeBanner } from "../components/feedback";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, Input, PageHeader, Select } from "../components/ui";
import { useAction, useAlertConfig, useAlerts } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import { api } from "../services/api";
import type { AlertConfig, Severity } from "../types/api";
import { DASH, formatRelative } from "../utils/format";

const EVENTS = ["INCIDENT_CRITICAL", "INCIDENT_WARNING", "INCIDENT_ESCALATED", "INCIDENT_RESOLVED", "RECOVERY_STARTED", "RECOVERY_SUCCEEDED", "RECOVERY_FAILED"];
const cfgSchema = z.object({ enabled: z.boolean(), min_severity: z.enum(["INFO", "WARNING", "CRITICAL"]), cooldown_seconds: z.coerce.number().int().min(0, "Min 0").max(86400, "Max 86400"), notify_events: z.array(z.string()) });
type CfgIn = z.input<typeof cfgSchema>; type CfgOut = z.output<typeof cfgSchema>;

function ConfigCard({ c }: { c: AlertConfig }) {
  const toast = useToast();
  const { register, handleSubmit, formState: { errors } } = useForm<CfgIn, unknown, CfgOut>({ resolver: zodResolver(cfgSchema), defaultValues: { enabled: c.enabled, min_severity: c.min_severity, cooldown_seconds: c.cooldown_seconds, notify_events: c.notify_events } });
  const save = useAction((v: CfgOut) => api.patch<AlertConfig>("/alerts/configuration", { channel: "TELEGRAM", ...v, min_severity: v.min_severity as Severity }), ["alert-config"]);
  const test = useAction(() => api.post<{ status: string }>("/alerts/test", {}), ["alerts", "overview"]);
  return (
    <Card title="Telegram notifications" actions={<Badge tone={c.channel_configured ? "ok" : "warn"}>{c.channel_configured ? "configured" : "not configured"}</Badge>}>
      {!c.channel_configured && <NoticeBanner>Telegram is optional and not configured. Set IGUARD_TELEGRAM_BOT_TOKEN and IGUARD_TELEGRAM_CHAT_ID in the environment; secrets are never shown here.</NoticeBanner>}
      <form noValidate className="grid gap-3 sm:grid-cols-2" onSubmit={handleSubmit((v) => save.mutate(v, { onSuccess: () => toast.success("Saved"), onError: (e) => toast.error(errorMessage(e)) }))}>
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" {...register("enabled")} /> Send notifications</label>
        <Field label="Minimum severity" htmlFor="al-sev"><Select id="al-sev" {...register("min_severity")}><option>INFO</option><option>WARNING</option><option>CRITICAL</option></Select></Field>
        <Field label="Cooldown (seconds)" htmlFor="al-cd" error={errors.cooldown_seconds?.message}><Input id="al-cd" type="number" {...register("cooldown_seconds")} /></Field>
        <fieldset className="sm:col-span-2"><legend className="label">Events</legend><div className="flex flex-wrap gap-4">{EVENTS.map((e) => <label key={e} className="flex items-center gap-2 text-sm"><input type="checkbox" value={e} {...register("notify_events")} /> {e.replaceAll("_", " ").toLowerCase()}</label>)}</div></fieldset>
        <Can role="ADMIN"><div className="flex gap-2 sm:col-span-2"><Button type="submit" variant="primary" loading={save.isPending}>Save</Button><Button type="button" disabled={!c.channel_configured} loading={test.isPending} onClick={() => test.mutate(undefined, { onSuccess: (r) => toast.info(`Test notification ${r.status.toLowerCase()}`), onError: (e) => toast.error(errorMessage(e)) })}>Send test</Button></div></Can>
      </form>
    </Card>
  );
}

export default function Alerts() {
  const t = useTableParams({});
  const q = useAlerts(t.query);
  const cfg = useAlertConfig();
  return (
    <>
      <PageHeader title="Alerts" subtitle="Live Alertmanager alerts and IGuard notification history." />
      <QueryBoundary query={q}>
        {(a) => (
          <div className="space-y-4">
            {!a.alertmanager_available && <NoticeBanner>Alertmanager is unreachable; live alerts cannot be shown. Notification history below is still available.</NoticeBanner>}
            <Card title={`Active alerts (${a.active.length})`} padded={false}>
              <DataTable rows={a.active} rowKey={(x) => `${x.name}-${x.started_at}-${JSON.stringify(x.labels)}`} empty={{ title: "No active alerts" }} columns={[
                { key: "sev", header: "Severity", render: (x) => (x.severity ? <SeverityBadge severity={x.severity.toUpperCase() as Severity} /> : DASH) },
                { key: "n", header: "Alert", render: (x) => <span className="font-medium">{x.name}</span> },
                { key: "s", header: "Summary", render: (x) => x.summary },
                { key: "t", header: "Since", render: (x) => formatRelative(x.started_at) },
                { key: "i", header: "Incident", render: (x) => (x.incident_id ? <Link className="text-brand" to={`/incidents/${x.incident_id}`}>View</Link> : DASH) },
              ]} />
            </Card>
            <Card title="Notification history" padded={false}>
              <DataTable rows={a.history.items} rowKey={(x) => `${x.name}-${x.started_at}`} empty={{ title: "No notifications sent yet" }} columns={[
                { key: "n", header: "Title", render: (x) => x.name }, { key: "st", header: "State", render: (x) => <Badge tone={x.state === "SENT" ? "ok" : x.state === "FAILED" ? "crit" : "neutral"}>{x.state}</Badge> },
                { key: "su", header: "Detail", render: (x) => <span className="line-clamp-2 text-xs text-ink-dim">{x.summary}</span> }, { key: "t", header: "When", render: (x) => formatRelative(x.started_at) },
              ]} />
              <Pagination page={{ ...a.history, pages: Math.max(1, Math.ceil(a.history.total / a.history.page_size)) }} onPage={t.setPage} />
            </Card>
          </div>
        )}
      </QueryBoundary>
      <div className="mt-4"><QueryBoundary query={cfg}>{(c) => <ConfigCard c={c} />}</QueryBoundary></div>
    </>
  );
}
