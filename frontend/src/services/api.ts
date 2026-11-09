import type { ApiErrorBody, TokenResponse } from "../types/api";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown, public requestId?: string) {
    super(message);
    this.name = "ApiError";
  }
}

const CSRF_KEY = "iguard.csrf";
let accessToken: string | null = null;
let authLostHandler: (() => void) | null = null;
let refreshInFlight: Promise<TokenResponse | null> | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (t: string | null) => { accessToken = t; },
};
export function onAuthLost(handler: (() => void) | null) { authLostHandler = handler; }

function csrf(): string | null { try { return sessionStorage.getItem(CSRF_KEY); } catch { return null; } }
export function setCsrf(v: string | null) {
  try { if (v) sessionStorage.setItem(CSRF_KEY, v); else sessionStorage.removeItem(CSRF_KEY); } catch { /* storage unavailable */ }
}
export function hasSessionHint(): boolean { return csrf() !== null; }

function qs(query?: Record<string, unknown>): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function parse(res: Response): Promise<unknown> {
  if (res.status === 204) return undefined;
  const text = await res.text();
  if (!text) return undefined;
  try { return JSON.parse(text); } catch { return text; }
}

function toError(res: Response, body: unknown): ApiError {
  const e = (body as ApiErrorBody | undefined)?.error;
  return new ApiError(res.status, e?.code ?? `http_${res.status}`, e?.message ?? res.statusText ?? "Request failed", e?.details, e?.request_id);
}

/** Rotating refresh tokens: concurrent callers MUST share one request or the rotation looks like token theft. */
export function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch("/api/v1/auth/refresh", {
          method: "POST", credentials: "include",
          headers: { "Content-Type": "application/json", ...(csrf() ? { "X-CSRF-Token": csrf() as string } : {}) },
          body: "{}",
        });
        if (!res.ok) { tokenStore.set(null); setCsrf(null); return null; }
        const data = (await res.json()) as TokenResponse;
        tokenStore.set(data.access_token); setCsrf(data.csrf_token);
        return data;
      } catch {
        return null;
      } finally {
        setTimeout(() => { refreshInFlight = null; }, 0);
      }
    })();
  }
  return refreshInFlight;
}

export interface RequestOptions { body?: unknown; query?: Record<string, unknown>; auth?: boolean; headers?: Record<string, string>; signal?: AbortSignal }

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, query, auth = true, headers = {}, signal } = opts;
  const attempt = async (): Promise<Response> => fetch(`/api/v1${path}${qs(query)}`, {
    method, credentials: "include", signal,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(auth && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  let res: Response;
  try { res = await attempt(); } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Cannot reach the IGuard API. Check your connection.");
  }
  if (res.status === 401 && auth) {
    const refreshed = await refreshSession();
    if (refreshed) res = await attempt();
    else { authLostHandler?.(); }
  }
  const data = await parse(res);
  if (!res.ok) throw toError(res, data);
  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, opts: Omit<RequestOptions, "body"> = {}) => request<T>("POST", path, { ...opts, body: body ?? {} }),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, { body }),
  del: <T = void>(path: string) => request<T>("DELETE", path),
};
