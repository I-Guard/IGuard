import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Can } from "../components/RequireRole";
import { Badge, Button, cx } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { useOverview } from "../hooks/queries";
import type { Role } from "../types/api";

const NAV: { to: string; label: string; role?: Role; group: string }[] = [
  { to: "/", label: "Overview", group: "Monitor" },
  { to: "/infrastructure", label: "Infrastructure", group: "Monitor" },
  { to: "/servers", label: "Servers", group: "Monitor" },
  { to: "/services", label: "Services", group: "Monitor" },
  { to: "/incidents", label: "Incidents", group: "Respond" },
  { to: "/recovery", label: "Recovery", group: "Respond" },
  { to: "/recovery/history", label: "Recovery history", group: "Respond" },
  { to: "/alerts", label: "Alerts", group: "Respond" },
  { to: "/logs", label: "Logs", group: "Analyze" },
  { to: "/reports", label: "Reports", group: "Analyze" },
  { to: "/audit-logs", label: "Audit logs", role: "ADMIN", group: "Admin" },
  { to: "/users", label: "Users", role: "ADMIN", group: "Admin" },
  { to: "/settings", label: "Settings", group: "Admin" },
];

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const groups = [...new Set(NAV.map((n) => n.group))];
  return (
    <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
      {groups.map((g) => (
        <div key={g}>
          <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{g}</div>
          {NAV.filter((n) => n.group === g).map((n) => {
            const link = (
              <NavLink key={n.to} to={n.to} end={n.to === "/" || n.to === "/recovery"} onClick={onNavigate}
                className={({ isActive }) => cx("block rounded-md px-2 py-1.5 text-sm", isActive ? "bg-brand/15 font-medium text-brand" : "text-ink-dim hover:bg-bg-hover hover:text-ink")}>
                {n.label}
              </NavLink>
            );
            return n.role ? <Can key={n.to} role={n.role}>{link}</Can> : link;
          })}
        </div>
      ))}
    </nav>
  );
}

export function AppLayout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const overview = useOverview();
  const promUp = overview.data?.monitoring.prometheus_available;
  return (
    <div className="flex h-full">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-bg-raised md:flex">
        <Brand />
        <Nav />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-bg-raised"><Brand /><Nav onNavigate={() => setOpen(false)} /></aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-bg-raised px-4">
          <button className="rounded p-2 text-ink-dim hover:bg-bg-hover md:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}>☰</button>
          <div className="hidden items-center gap-2 text-xs text-ink-dim sm:flex">
            <span>Monitoring stack:</span>
            {promUp === undefined ? <Badge>checking</Badge> : promUp ? <Badge tone="ok">Prometheus connected</Badge> : <Badge tone="crit">Prometheus unreachable</Badge>}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button className="text-right text-xs hover:text-brand" onClick={() => nav("/profile")} aria-label="Open profile">
              <div className="font-medium text-ink">{user?.full_name || user?.username}</div>
              <div className="text-ink-faint">{user?.roles.join(", ")}</div>
            </button>
            <Button size="sm" onClick={() => void logout().then(() => nav("/login"))}>Sign out</Button>
          </div>
        </header>
        <main id="main" className="flex-1 overflow-y-auto p-4 md:p-6"><Outlet /></main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex h-14 items-center gap-2 border-b border-line px-4">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><path fill="#4f8cff" d="M16 2 4 7v8c0 7 5 13 12 15 7-2 12-8 12-15V7z" /></svg>
      <div><div className="text-sm font-semibold leading-tight">IGuard</div><div className="text-[10px] leading-tight text-ink-faint">Monitor. Detect. Recover. Protect.</div></div>
    </div>
  );
}
