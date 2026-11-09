import { expect, test, type Page } from "@playwright/test";

const USER = process.env.E2E_USER;
const PASSWORD = process.env.E2E_PASSWORD;
const WEBHOOK_TOKEN = process.env.E2E_WEBHOOK_TOKEN;

test.describe("anonymous", () => {
  test("is redirected to the login page", async ({ page }) => {
    await page.goto("/servers");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: "Sign in to IGuard" })).toBeVisible();
  });

  test("rejects bad credentials with a uniform message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username or email").fill("nobody");
    await page.getByLabel("Password").fill("definitely-wrong");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText("Invalid credentials");
  });
});

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(USER!);
  await page.getByLabel("Password").fill(PASSWORD!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test.describe("authenticated", () => {
  test.skip(!USER || !PASSWORD, "set E2E_USER and E2E_PASSWORD");
  test.beforeEach(({ page }) => login(page));

  test("every page loads without an API error", async ({ page }) => {
    // Pages that depend on optional integrations (Prometheus/Loki) may legitimately report them as unavailable.
    const tolerant = new Set(["/", "/logs"]);
    const paths = ["/", "/infrastructure", "/servers", "/services", "/incidents", "/recovery", "/recovery/history", "/logs", "/alerts", "/reports", "/audit-logs", "/users", "/settings", "/profile"];
    for (const path of paths) {
      await page.goto(path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await expect(page.getByText("Loading…"), `stuck loading on ${path}`).toHaveCount(0, { timeout: 10_000 });
      if (!tolerant.has(path)) await expect(page.getByText("Something went wrong"), `API error on ${path}`).toHaveCount(0);
    }
  });

  test("keeps the session across a reload", async ({ page }) => {
    await page.reload();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  });

  test("creates a server and a service through the forms, and runs a check", async ({ page }) => {
    const name = `e2e-${Date.now()}`;
    await page.goto("/servers");
    await page.getByRole("button", { name: "Add server" }).click();
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByLabel("Hostname").fill("e2e.example.test");
    await page.getByRole("button", { name: "Create server" }).click();
    await expect(page.getByRole("cell", { name })).toBeVisible();

    await page.goto("/services");
    await page.getByRole("button", { name: "Add service" }).click();
    await page.getByLabel("Name", { exact: true }).fill(`${name}-svc`);
    await page.getByLabel("URL").fill("http://127.0.0.1:8000/api/v1/health");
    await page.getByRole("button", { name: "Create service" }).click();
    await page.getByRole("cell", { name: `${name}-svc` }).click();
    await page.getByRole("button", { name: "Run check now" }).click();
    await expect(page.getByText(/Check passed/)).toBeVisible();
  });

  test("shows validation errors without calling the API", async ({ page }) => {
    await page.goto("/servers");
    await page.getByRole("button", { name: "Add server" }).click();
    await page.getByRole("button", { name: "Create server" }).click();
    await expect(page.getByText("Name is required", { exact: true })).toBeVisible();
  });

  test("incident lifecycle from an Alertmanager webhook", async ({ page, request }) => {
    test.skip(!WEBHOOK_TOKEN, "set E2E_WEBHOOK_TOKEN (same value as IGUARD_WEBHOOK_TOKEN)");
    const alertname = `HostHighCpu`;
    const res = await request.post("/api/v1/alerts/webhook", {
      headers: { Authorization: `Bearer ${WEBHOOK_TOKEN}` },
      data: { alerts: [{ status: "firing", labels: { alertname, severity: "critical", instance: `e2e-${Date.now()}:9100` }, annotations: { summary: "E2E CPU alert" } }] },
    });
    expect(res.ok()).toBeTruthy();
    await page.goto("/incidents");
    await page.getByRole("cell", { name: "E2E CPU alert" }).first().click();
    await page.getByRole("button", { name: "Acknowledge" }).click();
    await expect(page.getByText("Acknowledged", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Resolve" }).click();
    await page.getByLabel("Resolution summary").fill("Resolved by the E2E test");
    await page.getByRole("dialog").getByRole("button", { name: "Resolve" }).click();
    await expect(page.getByText("Resolved by the E2E test").first()).toBeVisible();
  });

  test("signs out", async ({ page }) => {
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
  });
});
