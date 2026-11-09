import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { ServiceStatusBadge } from "../components/badges";
import { DataTable, Pagination } from "../components/DataTable";
import { QueryBoundary, errorMessage } from "../components/feedback";
import { Modal } from "../components/Modal";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, Input, PageHeader, Select, Textarea } from "../components/ui";
import { useAction, useServers, useServices } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import { api } from "../services/api";
import type { Service } from "../types/api";
import { formatMs, formatPercent, formatRelative } from "../utils/format";

export const serviceSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(128).regex(/^[A-Za-z0-9][A-Za-z0-9 _.-]*$/, "Letters, digits, space, _ . - only"),
  description: z.string().max(1024).optional(),
  server_id: z.string().optional(),
  check_type: z.enum(["HTTP", "HTTPS", "TCP"]),
  url: z.string().trim().max(1024).optional(),
  host: z.string().trim().max(255).optional(),
  port: z.string().optional(),
  expected_status_codes: z.string().regex(/^\s*\d{3}(\s*,\s*\d{3})*\s*$/, "Comma-separated HTTP codes, e.g. 200,204"),
  interval_seconds: z.coerce.number().int().min(5, "Min 5").max(86400),
  timeout_seconds: z.coerce.number().min(0.5, "Min 0.5").max(60),
  retry_threshold: z.coerce.number().int().min(1).max(20),
  latency_threshold_ms: z.coerce.number().int().min(10).max(120000),
  container_name: z.string().trim().max(128).optional(),
}).superRefine((v, ctx) => {
  if (v.check_type === "TCP") {
    if (!v.host) ctx.addIssue({ code: "custom", path: ["host"], message: "Host is required for TCP checks" });
    const p = Number(v.port);
    if (!v.port || !Number.isInteger(p) || p < 1 || p > 65535) ctx.addIssue({ code: "custom", path: ["port"], message: "Port 1-65535 required for TCP checks" });
  } else if (!v.url || !/^https?:\/\//i.test(v.url)) ctx.addIssue({ code: "custom", path: ["url"], message: "A http(s):// URL is required" });
});
type FormIn = z.input<typeof serviceSchema>;
type FormOut = z.output<typeof serviceSchema>;

export function ServiceForm({ initial, onDone, onCancel }: { initial?: Service; onDone: () => void; onCancel: () => void }) {
  const toast = useToast();
  const servers = useServers({ page_size: 100, sort: "name" });
  const { register, handleSubmit, watch, formState: { errors } } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(serviceSchema),
    defaultValues: {
      name: initial?.name ?? "", description: initial?.description ?? "", server_id: initial?.server_id ?? "", check_type: initial?.check_type ?? "HTTP",
      url: initial?.url ?? "", host: initial?.host ?? "", port: initial?.port ? String(initial.port) : "",
      expected_status_codes: (initial?.expected_status_codes ?? [200]).join(","), interval_seconds: initial?.interval_seconds ?? 30,
      timeout_seconds: initial?.timeout_seconds ?? 5, retry_threshold: initial?.retry_threshold ?? 3, latency_threshold_ms: initial?.latency_threshold_ms ?? 1000,
      container_name: initial?.container_name ?? "",
    },
  });
  const type = watch("check_type");
  const save = useAction((v: FormOut) => {
    const body = {
      name: v.name, description: v.description ?? "", server_id: v.server_id || null, check_type: v.check_type,
      url: v.check_type === "TCP" ? null : v.url, host: v.check_type === "TCP" ? v.host : null, port: v.check_type === "TCP" ? Number(v.port) : null,
      expected_status_codes: v.expected_status_codes.split(",").map((c) => Number(c.trim())), interval_seconds: v.interval_seconds,
      timeout_seconds: v.timeout_seconds, retry_threshold: v.retry_threshold, latency_threshold_ms: v.latency_threshold_ms, container_name: v.container_name || null,
    };
    return initial ? api.patch<Service>(`/services/${initial.id}`, body) : api.post<Service>("/services", body);
  }, ["services", "service", "overview"]);
  return (
    <form noValidate className="space-y-3" onSubmit={handleSubmit((v) => save.mutate(v, { onSuccess: () => { toast.success(initial ? "Service updated" : "Service created"); onDone(); }, onError: (e) => toast.error(errorMessage(e)) }))}>
      <Field label="Name" htmlFor="svc-name" error={errors.name?.message}><Input id="svc-name" {...register("name")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Check type" htmlFor="svc-type"><Select id="svc-type" {...register("check_type")}><option>HTTP</option><option>HTTPS</option><option>TCP</option></Select></Field>
        <Field label="Server" htmlFor="svc-server"><Select id="svc-server" {...register("server_id")}><option value="">— none —</option>{servers.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      </div>
      {type === "TCP" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Host" htmlFor="svc-host" error={errors.host?.message}><Input id="svc-host" {...register("host")} /></Field>
          <Field label="Port" htmlFor="svc-port" error={errors.port?.message}><Input id="svc-port" inputMode="numeric" {...register("port")} /></Field>
        </div>
      ) : (
        <>
          <Field label="URL" htmlFor="svc-url" error={errors.url?.message}><Input id="svc-url" placeholder="http://game-api:8080/health" {...register("url")} /></Field>
          <Field label="Expected status codes" htmlFor="svc-codes" error={errors.expected_status_codes?.message}><Input id="svc-codes" {...register("expected_status_codes")} /></Field>
        </>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Interval (s)" htmlFor="svc-int" error={errors.interval_seconds?.message}><Input id="svc-int" type="number" {...register("interval_seconds")} /></Field>
        <Field label="Timeout (s)" htmlFor="svc-to" error={errors.timeout_seconds?.message}><Input id="svc-to" type="number" step="0.5" {...register("timeout_seconds")} /></Field>
        <Field label="Retries" htmlFor="svc-ret" error={errors.retry_threshold?.message}><Input id="svc-ret" type="number" {...register("retry_threshold")} /></Field>
        <Field label="Latency (ms)" htmlFor="svc-lat" error={errors.latency_threshold_ms?.message}><Input id="svc-lat" type="number" {...register("latency_threshold_ms")} /></Field>
      </div>
      <Field label="Container name" htmlFor="svc-ctr" hint="Optional; used for log correlation." error={errors.container_name?.message}><Input id="svc-ctr" {...register("container_name")} /></Field>
      <Field label="Description" htmlFor="svc-desc"><Textarea id="svc-desc" rows={2} {...register("description")} /></Field>
      <div className="flex justify-end gap-2 pt-2"><Button type="button" onClick={onCancel}>Cancel</Button><Button type="submit" variant="primary" loading={save.isPending}>{initial ? "Save changes" : "Create service"}</Button></div>
    </form>
  );
}

export default function Services() {
  const nav = useNavigate();
  const t = useTableParams({ sort: "name" });
  const q = useServices(t.query);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title="Services" subtitle="Synthetic availability checks (HTTP, HTTPS, TCP)." actions={<Can role="ADMIN"><Button variant="primary" onClick={() => setCreating(true)}>Add service</Button></Can>} />
      <Card padded={false}>
        <div className="flex flex-wrap gap-3 border-b border-line p-3">
          <Input aria-label="Search services" placeholder="Search…" className="max-w-xs" value={t.filters.search ?? ""} onChange={(e) => t.setFilter("search", e.target.value)} />
          <Select aria-label="Status filter" className="max-w-[10rem]" value={t.filters.status ?? ""} onChange={(e) => t.setFilter("status", e.target.value)}>
            <option value="">All statuses</option>{["UP", "DEGRADED", "DOWN", "UNKNOWN"].map((s) => <option key={s}>{s}</option>)}
          </Select>
        </div>
        <QueryBoundary query={q}>
          {(p) => (
            <>
              <DataTable rows={p.items} rowKey={(s) => s.id} sort={t.sort} onSort={t.setSort} onRowClick={(s) => nav(`/services/${s.id}`)}
                empty={{ title: "No services", hint: "Add a service to start availability checks." }}
                columns={[
                  { key: "name", header: "Name", sortKey: "name", render: (s) => <span className="font-medium">{s.name}</span> },
                  { key: "status", header: "Status", render: (s) => <ServiceStatusBadge status={s.status} /> },
                  { key: "type", header: "Type", render: (s) => <Badge>{s.check_type}</Badge> },
                  { key: "server", header: "Server", render: (s) => s.server_name ?? "—" },
                  { key: "lat", header: "Latency", render: (s) => formatMs(s.last_response_ms) },
                  { key: "av", header: "Avail. 24h", render: (s) => formatPercent(s.availability_24h, 2) },
                  { key: "chk", header: "Last check", render: (s) => formatRelative(s.last_checked_at) },
                ]} />
              <Pagination page={p} onPage={t.setPage} />
            </>
          )}
        </QueryBoundary>
      </Card>
      <Modal open={creating} title="Add service" wide onClose={() => setCreating(false)}><ServiceForm onDone={() => setCreating(false)} onCancel={() => setCreating(false)} /></Modal>
    </>
  );
}
