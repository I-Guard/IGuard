import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { NoticeBanner, errorMessage } from "../components/feedback";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, Field, Input, KeyValue, PageHeader } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../services/api";
import type { User } from "../types/api";
import { formatDateTime } from "../utils/format";
import { passwordSchema } from "../utils/password";

const pwSchema = z.object({ current_password: z.string().min(1, "Enter your current password"), new_password: passwordSchema, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match" })
  .refine((v) => v.new_password !== v.current_password, { path: ["new_password"], message: "Must differ from the current password" });
type PwForm = z.infer<typeof pwSchema>;
const nameSchema = z.object({ full_name: z.string().trim().max(255) });
type NameForm = z.infer<typeof nameSchema>;

export default function Profile() {
  const { user, setUser, logout } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const loc = useLocation();
  const forced = !!user?.must_change_password || !!(loc.state as { forced?: boolean } | null)?.forced;
  const pw = useForm<PwForm>({ resolver: zodResolver(pwSchema) });
  const nm = useForm<NameForm>({ resolver: zodResolver(nameSchema), defaultValues: { full_name: user?.full_name ?? "" } });
  if (!user) return null;
  const changePw = pw.handleSubmit(async (v) => {
    try {
      await api.post("/auth/change-password", { current_password: v.current_password, new_password: v.new_password });
      toast.success("Password changed. Please sign in again.");
      await logout(); nav("/login");
    } catch (e) { toast.error(errorMessage(e)); }
  });
  const saveName = nm.handleSubmit(async (v) => {
    try { setUser(await api.patch<User>("/users/me", { full_name: v.full_name })); toast.success("Profile updated"); } catch (e) { toast.error(errorMessage(e)); }
  });
  return (
    <>
      <PageHeader title="Profile" />
      {forced && <NoticeBanner>You must change your password before using IGuard.</NoticeBanner>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Account">
          <KeyValue items={[["Username", user.username], ["Email", user.email], ["Roles", <span key="r" className="flex gap-1">{user.roles.map((r) => <Badge key={r}>{r}</Badge>)}</span>], ["Last login", formatDateTime(user.last_login_at)]]} />
          <form noValidate onSubmit={saveName} className="mt-4 flex items-end gap-2">
            <div className="flex-1"><Field label="Full name" htmlFor="p-name" error={nm.formState.errors.full_name?.message}><Input id="p-name" {...nm.register("full_name")} /></Field></div>
            <Button type="submit" loading={nm.formState.isSubmitting}>Save</Button>
          </form>
        </Card>
        <Card title="Change password">
          <form noValidate onSubmit={changePw} className="space-y-3">
            <Field label="Current password" htmlFor="pw-cur" error={pw.formState.errors.current_password?.message}><Input id="pw-cur" type="password" autoComplete="current-password" {...pw.register("current_password")} /></Field>
            <Field label="New password" htmlFor="pw-new" hint="Min 12 chars with upper, lower and a digit." error={pw.formState.errors.new_password?.message}><Input id="pw-new" type="password" autoComplete="new-password" {...pw.register("new_password")} /></Field>
            <Field label="Confirm new password" htmlFor="pw-conf" error={pw.formState.errors.confirm?.message}><Input id="pw-conf" type="password" autoComplete="new-password" {...pw.register("confirm")} /></Field>
            <Button type="submit" variant="primary" loading={pw.formState.isSubmitting}>Change password</Button>
          </form>
        </Card>
      </div>
    </>
  );
}
