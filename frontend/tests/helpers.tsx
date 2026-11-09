import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ToastProvider } from "../src/components/Toast";
import { AuthProvider } from "../src/contexts/AuthContext";
import { setCsrf, tokenStore } from "../src/services/api";
import type { Role, User } from "../src/types/api";

export const mkUser = (roles: Role[] = ["ADMIN"], extra: Partial<User> = {}): User => ({
  id: "u1", email: "a@example.com", username: "alice", full_name: "Alice", is_active: true, must_change_password: false,
  roles, last_login_at: null, created_at: "2026-01-01T00:00:00Z", ...extra,
});

type Reply = { status?: number; body?: unknown };
type Handler = (url: URL, body: unknown) => Reply | undefined;
export interface Call { method: string; path: string; body: unknown; headers: Headers }

/** Fetch mock keyed by "METHOD /path" (without /api/v1). Unmocked calls throw so tests fail loudly. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body, headers: new Headers(init.headers) });
    const r = routes[`${method} ${path}`];
    if (r === undefined) throw new Error(`Unmocked API call: ${method} ${path}`);
    const out: Reply | undefined = typeof r === "function" ? (r as Handler)(url, body) : { body: r };
    const status = out?.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(out?.body ?? {}), { status, headers: { "content-type": "application/json" } });
  }));
  return { calls, find: (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path) };
}

/** Arrange an already-signed-in session: the provider restores it through the (mocked) refresh endpoint. */
export function sessionRoute(user: User): Record<string, unknown> {
  return { "POST /auth/refresh": { access_token: "tok", token_type: "bearer", expires_in: 900, csrf_token: "csrf", user } };
}
export function arrangeSession() { tokenStore.set(null); setCsrf("csrf"); }

export function renderApp(ui: ReactElement, route = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[route]}><ToastProvider><AuthProvider>{ui}</AuthProvider></ToastProvider></MemoryRouter></QueryClientProvider>,
  );
}
