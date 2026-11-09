import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import type { Role } from "../types/api";
import { LoadingState } from "./feedback";

/** Route guard: authentication + optional minimum role. The backend enforces the same rules. */
export function RequireAuth({ children, role }: { children: ReactNode; role?: Role }) {
  const { status, hasRole, user } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <LoadingState label="Restoring session…" />;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  if (user?.must_change_password && loc.pathname !== "/profile") return <Navigate to="/profile" replace state={{ forced: true }} />;
  if (role && !hasRole(role)) {
    return <div role="alert" className="card mx-auto mt-16 max-w-md p-6 text-center"><h1 className="text-lg font-semibold">Access denied</h1><p className="mt-2 text-sm text-ink-dim">This page requires the {role} role.</p></div>;
  }
  return <>{children}</>;
}

/** Hides UI that the current role cannot use (purely cosmetic; never a security control). */
export function Can({ role, children }: { role: Role; children: ReactNode }) {
  const { hasRole } = useAuth();
  return hasRole(role) ? <>{children}</> : null;
}
