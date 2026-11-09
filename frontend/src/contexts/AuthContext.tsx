import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, hasSessionHint, onAuthLost, refreshSession, setCsrf, tokenStore } from "../services/api";
import type { Role, TokenResponse, User } from "../types/api";
import { hasRole as roleCheck } from "../utils/roles";

type Status = "loading" | "authenticated" | "anonymous";
interface AuthValue {
  user: User | null; status: Status;
  login: (identifier: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  setUser: (u: User) => void;
  hasRole: (min: Role) => boolean;
}
const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const qc = useQueryClient();

  const clear = useCallback(() => {
    tokenStore.set(null); setCsrf(null); setUser(null); setStatus("anonymous"); qc.clear();
  }, [qc]);

  useEffect(() => { onAuthLost(clear); return () => onAuthLost(null); }, [clear]);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!hasSessionHint()) { setStatus("anonymous"); return; }
      const data = await refreshSession();
      if (!alive) return;
      if (data) { setUser(data.user); setStatus("authenticated"); } else setStatus("anonymous");
    })();
    return () => { alive = false; };
  }, []);

  const login = useCallback(async (identifier: string, password: string) => {
    const data = await api.post<TokenResponse>("/auth/login", { identifier, password }, { auth: false });
    tokenStore.set(data.access_token); setCsrf(data.csrf_token);
    setUser(data.user); setStatus("authenticated");
    return data.user;
  }, []);

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch { /* session may already be gone */ }
    clear();
  }, [clear]);

  const value = useMemo<AuthValue>(() => ({
    user, status, login, logout, setUser,
    hasRole: (min) => (user ? roleCheck(user.roles, min) : false),
  }), [user, status, login, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside <AuthProvider>");
  return v;
}
