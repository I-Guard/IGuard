import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { RequireAuth } from "../src/components/RequireRole";
import IncidentDetails from "../src/pages/IncidentDetails";
import Overview from "../src/pages/Overview";
import Recovery from "../src/pages/Recovery";
import Servers from "../src/pages/Servers";
import Services from "../src/pages/Services";
import Users from "../src/pages/Users";
import type { Incident, Overview as OverviewT, RecoveryAction, Role } from "../src/types/api";
import { arrangeSession, mkUser, mockApi, renderApp, sessionRoute } from "./helpers";

const emptyPage = { items: [], total: 0, page: 1, page_size: 25, pages: 1 };
const incident = (o: Partial<Incident> = {}): Incident => ({
  id: "i1", title: "game-api down", description: "", severity: "CRITICAL", category: "SERVICE_DOWN", status: "DETECTED", source: "detector", fingerprint: "f",
  server_id: null, server_name: null, service_id: "s1", service_name: "game-api", acknowledged_by: null, assigned_to: null, root_cause: null, resolution_summary: null,
  occurrences: 1, flap_count: 0, is_flapping: false, escalation_level: 0, correlation_group: null, context: null,
  first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-01T00:00:00Z", created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z", acknowledged_at: null, resolved_at: null, ...o,
});
const overview = (o: Partial<OverviewT> = {}): OverviewT => ({
  generated_at: "2026-11-01T00:00:00Z", monitoring: { prometheus_available: true },
  servers: { total: 2, healthy: 1, degraded: 1, unhealthy: 0, unknown: 0 }, incidents: { active: 1, critical: 1 },
  services: { total: 5, up: 4, degraded: 0, down: 1, unknown: 0, availability_24h_percent: 99.5, avg_latency_ms_15m: 42 },
  utilization: { cpu_percent: 12.5, memory_percent: 40, disk_percent: 55 }, recent_incidents: [incident()], recent_alerts: [], recovery_activity_24h: {}, ...o,
});
const action = (o: Partial<RecoveryAction> = {}): RecoveryAction => ({
  id: "a1", key: "restart-game-api", name: "Restart game-api", description: "Restart the container", action_type: "docker_restart", target: "iguard-game-api",
  service_id: "s1", service_name: "game-api", sensitive: false, requires_dry_run: true, auto_trigger: false, trigger_categories: [], enabled: true, cooldown_seconds: 300,
  timeout_seconds: 30, max_attempts_per_hour: 3, breaker_threshold: 3, breaker_reset_seconds: 600, min_role: "OPERATOR", circuit_open: false, cooldown_remaining_seconds: 0,
  last_execution_at: null, last_status: null, ...o,
});
const as = (role: Role) => { const u = mkUser([role]); arrangeSession(); return u; };

const overviewExtras = {
  "GET /services": emptyPage, "GET /servers": emptyPage,
  "GET /reports/summary": { incidents_total: 0, incidents_open: 0, mttr_minutes: null, by_severity: {}, by_category: {}, recoveries: {}, average_availability_percent: null },
  "GET /reports/incidents": { per_day: [], top_recurring: [], flapping: 0, by_status: {} },
};

describe("Overview", () => {
  it("renders live data", async () => {
    const u = as("VIEWER");
    mockApi({ ...sessionRoute(u), ...overviewExtras, "GET /overview": overview() });
    renderApp(<Overview />);
    expect(await screen.findByText("4/5")).toBeInTheDocument();
    expect(screen.getByText("Major disruption")).toBeInTheDocument();
    expect(screen.getByText(/1 critical incident open/)).toBeInTheDocument();
    expect(screen.getByText("99.50%")).toBeInTheDocument();
    expect(screen.getByText("game-api down")).toBeInTheDocument();
  });

  it("shows no-data, not zero, when Prometheus is unavailable", async () => {
    const u = as("VIEWER");
    mockApi({ ...sessionRoute(u), ...overviewExtras, "GET /overview": overview({ monitoring: { prometheus_available: false }, utilization: { cpu_percent: null, memory_percent: null, disk_percent: null } }) });
    renderApp(<Overview />);
    expect(await screen.findByText(/Prometheus is unreachable/)).toBeInTheDocument();
    expect(screen.getAllByText("no data")).toHaveLength(3);
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("surfaces API errors with a retry control", async () => {
    const u = as("VIEWER");
    mockApi({ ...sessionRoute(u), "GET /overview": () => ({ status: 500, body: { error: { code: "internal_error", message: "boom" } } }) });
    renderApp(<Overview />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});

describe("Overview service tiles", () => {
  it("lists services worst-first and links to details", async () => {
    const u = as("VIEWER");
    const svc = (id: string, name: string, status: string) => ({ id, name, status, last_response_ms: 12, availability_24h: 99.9, check_type: "HTTP" });
    mockApi({ ...sessionRoute(u), ...overviewExtras, "GET /overview": overview(), "GET /services": { ...emptyPage, items: [svc("a", "alpha", "UP"), svc("b", "bravo", "DOWN")], total: 2 } });
    renderApp(<Overview />);
    const links = await screen.findAllByRole("link", { name: /: (UP|DOWN)$/ });
    expect(links.map((l) => l.getAttribute("aria-label"))).toEqual(["bravo: DOWN", "alpha: UP"]);
    expect(links[0]).toHaveAttribute("href", "/services/b");
  });

  it("shows an empty trend state when no server exists", async () => {
    const u = as("VIEWER");
    mockApi({ ...sessionRoute(u), ...overviewExtras, "GET /overview": overview() });
    renderApp(<Overview />);
    expect(await screen.findByText("No servers yet")).toBeInTheDocument();
  });
});

describe("permission-based UI", () => {
  it("hides admin actions from a viewer", async () => {
    const u = as("VIEWER");
    mockApi({ ...sessionRoute(u), "GET /servers": emptyPage, "GET /services": emptyPage });
    renderApp(<Servers />);
    await screen.findByText("No servers");
    expect(screen.queryByRole("button", { name: "Add server" })).not.toBeInTheDocument();
  });

  it("shows admin actions to an admin", async () => {
    const u = as("ADMIN");
    mockApi({ ...sessionRoute(u), "GET /servers": emptyPage });
    renderApp(<Servers />);
    expect(await screen.findByRole("button", { name: "Add server" })).toBeInTheDocument();
  });

  it("blocks admin-only routes for operators", async () => {
    const u = as("OPERATOR");
    mockApi({ ...sessionRoute(u) });
    renderApp(<Routes><Route path="/users" element={<RequireAuth role="ADMIN"><Users /></RequireAuth>} /></Routes>, "/users");
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });

  it("redirects anonymous visitors to login", async () => {
    mockApi({});
    sessionStorage.clear();
    renderApp(<Routes><Route path="/login" element={<div>LOGIN</div>} /><Route path="/" element={<RequireAuth><div>SECRET</div></RequireAuth>} /></Routes>);
    expect(await screen.findByText("LOGIN")).toBeInTheDocument();
    expect(screen.queryByText("SECRET")).not.toBeInTheDocument();
  });
});

describe("incident actions", () => {
  const routes = (u: ReturnType<typeof mkUser>, i = incident()) => ({
    ...sessionRoute(u), "GET /incidents/i1": { ...i, related: [] }, "GET /incidents/i1/timeline": [], "GET /recovery/actions": [action()], "GET /users/assignable": [],
  });
  const tree = <Routes><Route path="/incidents/:id" element={<IncidentDetails />} /></Routes>;

  it("lets an operator acknowledge", async () => {
    const u = as("OPERATOR");
    const api = mockApi({ ...routes(u), "POST /incidents/i1/acknowledge": incident({ status: "ACKNOWLEDGED" }) });
    renderApp(tree, "/incidents/i1");
    await userEvent.click(await screen.findByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(api.find("POST", "/incidents/i1/acknowledge")).toHaveLength(1));
  });

  it("hides actions from viewers", async () => {
    const u = as("VIEWER");
    mockApi(routes(u));
    renderApp(tree, "/incidents/i1");
    await screen.findByText("game-api down");
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
  });

  it("requires a resolution summary (form validation)", async () => {
    const u = as("OPERATOR");
    const api = mockApi({ ...routes(u), "POST /incidents/i1/resolve": incident({ status: "RESOLVED" }) });
    renderApp(tree, "/incidents/i1");
    await userEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.click(within(dlg).getByRole("button", { name: "Resolve" }));
    expect(await within(dlg).findByText(/Describe the resolution/)).toBeInTheDocument();
    expect(api.find("POST", "/incidents/i1/resolve")).toHaveLength(0);
    await userEvent.type(within(dlg).getByLabelText("Resolution summary"), "Restarted the container");
    await userEvent.click(within(dlg).getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(api.find("POST", "/incidents/i1/resolve")[0]?.body).toMatchObject({ resolution_summary: "Restarted the container" }));
  });
});

describe("recovery operations", () => {
  it("sends an idempotency key on execute and a dry run without one", async () => {
    const u = as("OPERATOR");
    const done = { id: "e1", action_id: "a1", status: "SUCCEEDED", dry_run: false, simulated: false, trigger: "MANUAL", output: "ok" };
    const api = mockApi({ ...sessionRoute(u), "GET /recovery/actions": [action()], "POST /recovery/actions/a1/dry-run": { ...done, status: "DRY_RUN_OK", dry_run: true }, "POST /recovery/actions/a1/execute": done });
    renderApp(<Recovery />);
    await userEvent.click(await screen.findByRole("button", { name: "Dry run" }));
    await waitFor(() => expect(api.find("POST", "/recovery/actions/a1/dry-run")).toHaveLength(1));
    await userEvent.click(screen.getByRole("button", { name: "Execute" }));
    await waitFor(() => expect(api.find("POST", "/recovery/actions/a1/execute")).toHaveLength(1));
    expect(api.find("POST", "/recovery/actions/a1/execute")[0].headers.get("Idempotency-Key")).toMatch(/^ui-/);
  });

  it("requires typed confirmation for sensitive actions", async () => {
    const u = as("ADMIN");
    const api = mockApi({ ...sessionRoute(u), "GET /recovery/actions": [action({ sensitive: true, min_role: "ADMIN", key: "restart-wallet-mock", name: "Restart wallet" })], "POST /recovery/actions/a1/execute": { id: "e", status: "SUCCEEDED", dry_run: false } });
    renderApp(<Recovery />);
    await userEvent.click(await screen.findByRole("button", { name: "Execute" }));
    const dlg = await screen.findByRole("dialog");
    const go = within(dlg).getByRole("button", { name: "Execute" });
    expect(go).toBeDisabled();
    await userEvent.type(within(dlg).getByLabelText(/Type/), "restart-wallet-mock");
    expect(go).toBeEnabled();
    await userEvent.click(go);
    await waitFor(() => expect(api.find("POST", "/recovery/actions/a1/execute")[0]?.body).toMatchObject({ confirm: true }));
  });

  it("disables execute while the circuit breaker is open", async () => {
    const u = as("OPERATOR");
    mockApi({ ...sessionRoute(u), "GET /recovery/actions": [action({ circuit_open: true })] });
    renderApp(<Recovery />);
    expect(await screen.findByRole("button", { name: "Execute" })).toBeDisabled();
    expect(screen.getByText(/Circuit breaker open/)).toBeInTheDocument();
  });

  it("disables execute for a viewer-visible action requiring a higher role", async () => {
    const u = as("OPERATOR");
    mockApi({ ...sessionRoute(u), "GET /recovery/actions": [action({ min_role: "ADMIN" })] });
    renderApp(<Recovery />);
    expect(await screen.findByRole("button", { name: "Execute" })).toBeDisabled();
  });
});

describe("forms", () => {
  it("validates the service form per check type", async () => {
    const u = as("ADMIN");
    const api = mockApi({ ...sessionRoute(u), "GET /services": emptyPage, "GET /servers": emptyPage, "POST /services": { id: "s" } });
    renderApp(<Services />);
    await userEvent.click(await screen.findByRole("button", { name: "Add service" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.click(within(dlg).getByRole("button", { name: "Create service" }));
    expect(await within(dlg).findByText("Name is required")).toBeInTheDocument();
    expect(within(dlg).getByText("A http(s):// URL is required")).toBeInTheDocument();
    await userEvent.selectOptions(within(dlg).getByLabelText("Check type"), "TCP");
    expect(await within(dlg).findByLabelText("Port")).toBeInTheDocument();
    expect(api.find("POST", "/services")).toHaveLength(0);
  });

  it("creates a user with a policy-compliant password only", async () => {
    const u = as("ADMIN");
    const api = mockApi({ ...sessionRoute(u), "GET /users": emptyPage, "POST /users": { id: "n" } });
    renderApp(<Users />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.type(within(dlg).getByLabelText("Email"), "bob@example.com");
    await userEvent.type(within(dlg).getByLabelText("Username"), "bob");
    await userEvent.type(within(dlg).getByLabelText("Initial password"), "weak");
    await userEvent.click(within(dlg).getByRole("button", { name: "Create user" }));
    expect(await within(dlg).findByText("At least 12 characters")).toBeInTheDocument();
    expect(api.find("POST", "/users")).toHaveLength(0);
    await userEvent.clear(within(dlg).getByLabelText("Initial password"));
    await userEvent.type(within(dlg).getByLabelText("Initial password"), "Sufficiently-Long-1");
    await userEvent.click(within(dlg).getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(api.find("POST", "/users")[0]?.body).toMatchObject({ username: "bob", role: "VIEWER", must_change_password: true }));
  });
});

describe("audit logs", () => {
  it("filters by the backend's uppercase outcome values", async () => {
    const u = as("ADMIN");
    const api = mockApi({ ...sessionRoute(u), "GET /audit-logs": emptyPage });
    const { default: AuditLogs } = await import("../src/pages/AuditLogs");
    renderApp(<AuditLogs />);
    await userEvent.selectOptions(await screen.findByLabelText("Outcome"), "FAILURE");
    await waitFor(() => expect(api.find("GET", "/audit-logs").some((c) => c.path === "/audit-logs")).toBe(true));
    await waitFor(() => expect(JSON.stringify(vi.mocked(fetch).mock.calls.map((c) => String(c[0])))).toContain("outcome=FAILURE"));
  });
});

describe("logs explorer", () => {
  it("does not refetch in a loop (stable query key) and shows the upstream error", async () => {
    const u = as("VIEWER");
    const api = mockApi({ ...sessionRoute(u), "GET /logs": () => ({ status: 503, body: { error: { code: "upstream_unavailable", message: "Loki unavailable" } } }) });
    const { default: Logs } = await import("../src/pages/Logs");
    renderApp(<Logs />);
    expect(await screen.findByText(/Loki unavailable/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 300));
    expect(api.find("GET", "/logs")).toHaveLength(1);
  });
});
