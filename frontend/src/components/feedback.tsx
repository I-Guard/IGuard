import type { ReactNode } from "react";
import { ApiError } from "../services/api";
import { Button, Spinner } from "./ui";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center justify-center gap-3 py-12 text-sm text-ink-dim" role="status"><Spinner />{label}</div>;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.status === 0 ? e.message : e.status === 503 ? `${e.message}. The backing monitoring service is unavailable.` : e.message;
  return e instanceof Error ? e.message : "Unexpected error";
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-crit/40 bg-crit/10 p-4 text-sm">
      <p className="font-medium text-crit">Something went wrong</p>
      <p className="mt-1 text-ink-dim">{errorMessage(error)}</p>
      {error instanceof ApiError && error.requestId && <p className="mt-1 font-mono text-xs text-ink-faint">request id: {error.requestId}</p>}
      {onRetry && <Button className="mt-3" size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="max-w-md text-xs text-ink-faint">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function NoticeBanner({ tone = "warn", children }: { tone?: "warn" | "info" | "crit"; children: ReactNode }) {
  const cls = tone === "crit" ? "border-crit/40 bg-crit/10 text-crit" : tone === "info" ? "border-info/40 bg-info/10 text-info" : "border-warn/40 bg-warn/10 text-warn";
  return <div role="status" className={`mb-4 rounded-md border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

/** Renders loading / error / content for a TanStack query result. */
export function QueryBoundary<T>({ query, children }: { query: { isLoading: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown }; children: (data: T) => ReactNode }) {
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (query.data === undefined) return null;
  return <>{children(query.data)}</>;
}
