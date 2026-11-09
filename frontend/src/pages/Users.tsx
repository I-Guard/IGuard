import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { DataTable, Pagination } from "../components/DataTable";
import { QueryBoundary, errorMessage } from "../components/feedback";
import { ConfirmDialog, Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, Input, PageHeader, Select } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { useAction, useUsers } from "../hooks/queries";
import { useTableParams } from "../hooks/useTableParams";
import { api } from "../services/api";
import type { Role, User } from "../types/api";
import { formatRelative } from "../utils/format";
import { passwordSchema } from "../utils/password";

const createSchema = z.object({
  email: z.string().trim().email("Enter a valid email"),
  username: z.string().trim().regex(/^[A-Za-z0-9_.-]{3,64}$/, "3-64 chars: letters, digits, _ . -"),
  full_name: z.string().max(255).optional(),
  role: z.enum(["ADMIN", "OPERATOR", "VIEWER"]),
  password: passwordSchema,
});
type CreateForm = z.infer<typeof createSchema>;

function CreateUser({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const { register, handleSubmit, formState: { errors } } = useForm<CreateForm>({ resolver: zodResolver(createSchema), defaultValues: { role: "VIEWER" } });
  const save = useAction((v: CreateForm) => api.post<User>("/users", { ...v, must_change_password: true }), ["users", "assignable"]);
  return (
    <form noValidate className="space-y-3" onSubmit={handleSubmit((v) => save.mutate(v, { onSuccess: () => { toast.success("User created; they must change the password at first login"); onDone(); }, onError: (e) => toast.error(errorMessage(e)) }))}>
      <Field label="Email" htmlFor="u-email" error={errors.email?.message}><Input id="u-email" type="email" autoComplete="off" {...register("email")} /></Field>
      <Field label="Username" htmlFor="u-name" error={errors.username?.message}><Input id="u-name" autoComplete="off" {...register("username")} /></Field>
      <Field label="Full name" htmlFor="u-full" error={errors.full_name?.message}><Input id="u-full" {...register("full_name")} /></Field>
      <Field label="Role" htmlFor="u-role"><Select id="u-role" {...register("role")}><option>VIEWER</option><option>OPERATOR</option><option>ADMIN</option></Select></Field>
      <Field label="Initial password" htmlFor="u-pw" hint="Min 12 chars with upper, lower and a digit." error={errors.password?.message}><Input id="u-pw" type="password" autoComplete="new-password" {...register("password")} /></Field>
      <div className="flex justify-end gap-2 pt-2"><Button type="button" onClick={onDone}>Cancel</Button><Button type="submit" variant="primary" loading={save.isPending}>Create user</Button></div>
    </form>
  );
}

export default function Users() {
  const t = useTableParams({ sort: "username" });
  const q = useUsers(t.query);
  const toast = useToast();
  const { user: me } = useAuth();
  const [creating, setCreating] = useState(false);
  const [target, setTarget] = useState<User | null>(null);
  const update = useAction((a: { id: string; body: Record<string, unknown> }) => api.patch<User>(`/users/${a.id}`, a.body), ["users", "assignable"]);
  const del = useAction((id: string) => api.del(`/users/${id}`), ["users", "assignable"]);
  const patch = (u: User, body: Record<string, unknown>, msg: string) => update.mutate({ id: u.id, body }, { onSuccess: () => toast.success(msg), onError: (e) => toast.error(errorMessage(e)) });
  return (
    <>
      <PageHeader title="Users" subtitle="Accounts and roles." actions={<Button variant="primary" onClick={() => setCreating(true)}>Add user</Button>} />
      <Card padded={false}>
        <div className="border-b border-line p-3"><Input aria-label="Search users" placeholder="Search…" className="max-w-xs" value={t.filters.search ?? ""} onChange={(e) => t.setFilter("search", e.target.value)} /></div>
        <QueryBoundary query={q}>
          {(p) => (<>
            <DataTable rows={p.items} rowKey={(u) => u.id} sort={t.sort} onSort={t.setSort} empty={{ title: "No users" }} columns={[
              { key: "u", header: "User", sortKey: "username", render: (u) => <div><div className="font-medium">{u.username}{u.id === me?.id && <> <Badge tone="info">you</Badge></>}</div><div className="text-xs text-ink-faint">{u.email}</div></div> },
              { key: "r", header: "Role", render: (u) => <Select aria-label={`Role for ${u.username}`} className="!w-32 !py-1" value={u.roles[0]} disabled={u.id === me?.id} onChange={(e) => patch(u, { role: e.target.value as Role }, "Role updated")}><option>VIEWER</option><option>OPERATOR</option><option>ADMIN</option></Select> },
              { key: "s", header: "Status", render: (u) => <Badge tone={u.is_active ? "ok" : "neutral"}>{u.is_active ? "active" : "disabled"}</Badge> },
              { key: "l", header: "Last login", render: (u) => formatRelative(u.last_login_at) },
              { key: "a", header: "", render: (u) => u.id === me?.id ? null : (
                <div className="flex justify-end gap-2"><Button size="sm" onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? "User disabled" : "User enabled")}>{u.is_active ? "Disable" : "Enable"}</Button><Button size="sm" variant="danger" onClick={() => setTarget(u)}>Delete</Button></div>) },
            ]} />
            <Pagination page={p} onPage={t.setPage} />
          </>)}
        </QueryBoundary>
      </Card>
      <Modal open={creating} title="Add user" onClose={() => setCreating(false)}><CreateUser onDone={() => setCreating(false)} /></Modal>
      <ConfirmDialog open={!!target} danger title="Delete user" confirmLabel="Delete" loading={del.isPending} onCancel={() => setTarget(null)}
        message={<>Permanently delete <strong>{target?.username}</strong>? Their sessions are revoked. Audit history is retained.</>}
        onConfirm={() => target && del.mutate(target.id, { onSuccess: () => { toast.success("User deleted"); setTarget(null); }, onError: (e) => { toast.error(errorMessage(e)); setTarget(null); } })} />
    </>
  );
}
