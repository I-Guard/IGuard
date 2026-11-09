import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { Button, Field, Input } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { ApiError } from "../services/api";

const schema = z.object({ identifier: z.string().trim().min(1, "Enter your username or email"), password: z.string().min(1, "Enter your password") });
type Form = z.infer<typeof schema>;

export default function Login() {
  const { login, status } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  const from = (loc.state as { from?: string } | null)?.from ?? "/";
  if (status === "authenticated") return <Navigate to={from} replace />;

  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      const u = await login(v.identifier, v.password);
      nav(u.must_change_password ? "/profile" : from, { replace: true });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setError("Too many attempts. Please wait a few minutes and try again.");
      else if (e instanceof ApiError && e.status === 401) setError("Invalid credentials.");
      else setError("Sign-in failed. Check your connection and try again.");
    }
  });

  return (
    <main className="flex min-h-full items-center justify-center p-4">
      <form onSubmit={onSubmit} noValidate className="card w-full max-w-sm space-y-4 p-6" aria-label="Sign in">
        <div>
          <h1 className="text-xl font-semibold">Sign in to IGuard</h1>
          <p className="mt-1 text-sm text-ink-dim">iGaming Infrastructure Guardian</p>
        </div>
        {error && <div role="alert" className="rounded-md border border-crit/40 bg-crit/10 px-3 py-2 text-sm text-crit">{error}</div>}
        <Field label="Username or email" htmlFor="identifier" error={errors.identifier?.message}>
          <Input id="identifier" autoComplete="username" autoFocus {...register("identifier")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" {...register("password")} />
        </Field>
        <Button type="submit" variant="primary" loading={isSubmitting} className="w-full">Sign in</Button>
      </form>
    </main>
  );
}
