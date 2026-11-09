import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { HealthBadge } from "../components/badges";
import { DataTable } from "../components/DataTable";
import { Pagination } from "../components/DataTable";
import { Modal } from "../components/Modal";
import { QueryBoundary, errorMessage } from "../components/feedback";
import { Can } from "../components/RequireRole";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, Input, PageHeader, Textarea } from "../components/ui";
import { useAction, useServers } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import { api } from "../services/api";
import type { Server } from "../types/api";

export const serverSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(128).regex(/^[A-Za-z0-9][A-Za-z0-9 _.-]*$/, "Letters, digits, space, _ . - only"),
  hostname: z.string().trim().min(1, "Hostname is required").max(255),
  ip_address: z.string().trim().max(64).optional(),
  environment: z.string().trim().min(1).max(32),
  prometheus_instance: z.string().trim().max(255).optional(),
  description: z.string().max(1024).optional(),
});
type Form = z.infer<typeof serverSchema>;

export function ServerForm({ initial, onDone, onCancel }: { initial?: Server; onDone: () => void; onCancel: () => void }) {
  const toast = useToast();
  const { register, handleSubmit, formState: { errors } } = useForm<Form>({
    resolver: zodResolver(serverSchema),
    defaultValues: { name: initial?.name ?? "", hostname: initial?.hostname ?? "", ip_address: initial?.ip_address ?? "", environment: initial?.environment ?? "demo", prometheus_instance: initial?.prometheus_instance ?? "", description: initial?.description ?? "" },
  });
  const save = useAction((v: Form) => {
    const body = { ...v, ip_address: v.ip_address || null, prometheus_instance: v.prometheus_instance || null };
    return initial ? api.patch<Server>(`/servers/${initial.id}`, body) : api.post<Server>("/servers", body);
  }, ["servers", "server", "overview"]);
  return (
    <form noValidate className="space-y-3" onSubmit={handleSubmit((v) => save.mutate(v, { onSuccess: () => { toast.success(initial ? "Server updated" : "Server created"); onDone(); }, onError: (e) => toast.error(errorMessage(e)) }))}>
      <Field label="Name" htmlFor="srv-name" error={errors.name?.message}><Input id="srv-name" {...register("name")} /></Field>
      <Field label="Hostname" htmlFor="srv-host" error={errors.hostname?.message}><Input id="srv-host" {...register("hostname")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="IP address" htmlFor="srv-ip" error={errors.ip_address?.message}><Input id="srv-ip" {...register("ip_address")} /></Field>
        <Field label="Environment" htmlFor="srv-env" error={errors.environment?.message}><Input id="srv-env" {...register("environment")} /></Field>
      </div>
      <Field label="Prometheus instance" htmlFor="srv-prom" hint="Label value of `instance` for this host's node_exporter, e.g. node-exporter:9100" error={errors.prometheus_instance?.message}><Input id="srv-prom" {...register("prometheus_instance")} /></Field>
      <Field label="Description" htmlFor="srv-desc" error={errors.description?.message}><Textarea id="srv-desc" rows={2} {...register("description")} /></Field>
      <div className="flex justify-end gap-2 pt-2"><Button type="button" onClick={onCancel}>Cancel</Button><Button type="submit" variant="primary" loading={save.isPending}>{initial ? "Save changes" : "Create server"}</Button></div>
    </form>
  );
}

export default function Servers() {
  const nav = useNavigate();
  const t = useTableParams({ sort: "name" });
  const q = useServers(t.query);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title="Servers" subtitle="Hosts monitored through node_exporter."
        actions={<Can role="ADMIN"><Button variant="primary" onClick={() => setCreating(true)}>Add server</Button></Can>} />
      <Card padded={false}>
        <div className="flex flex-wrap gap-3 border-b border-line p-3">
          <Input aria-label="Search servers" placeholder="Search name or hostname…" className="max-w-xs" value={t.filters.search ?? ""} onChange={(e) => t.setFilter("search", e.target.value)} />
          <Input aria-label="Environment" placeholder="Environment" className="max-w-[10rem]" value={t.filters.environment ?? ""} onChange={(e) => t.setFilter("environment", e.target.value)} />
        </div>
        <QueryBoundary query={q}>
          {(p) => (
            <>
              <DataTable rows={p.items} rowKey={(s) => s.id} sort={t.sort} onSort={t.setSort} onRowClick={(s) => nav(`/servers/${s.id}`)}
                empty={{ title: "No servers", hint: "Add a server to start collecting host metrics." }}
                columns={[
                  { key: "name", header: "Name", sortKey: "name", render: (s) => <span className="font-medium">{s.name}</span> },
                  { key: "host", header: "Hostname", sortKey: "hostname", render: (s) => s.hostname },
                  { key: "env", header: "Env", render: (s) => <Badge>{s.environment}</Badge> },
                  { key: "health", header: "Health", render: (s) => <HealthBadge health={s.health} /> },
                  { key: "svc", header: "Services", render: (s) => s.service_count },
                  { key: "inc", header: "Active incidents", render: (s) => s.active_incidents },
                ]} />
              <Pagination page={p} onPage={t.setPage} />
            </>
          )}
        </QueryBoundary>
      </Card>
      <Modal open={creating} title="Add server" onClose={() => setCreating(false)}><ServerForm onDone={() => setCreating(false)} onCancel={() => setCreating(false)} /></Modal>
    </>
  );
}
