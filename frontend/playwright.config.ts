import { defineConfig, devices } from "@playwright/test";

/**
 * E2E runs against a real backend + built frontend. Start the backend first (see docs/TESTING.md),
 * then: E2E_BASE_URL=http://127.0.0.1:4173 E2E_USER=... E2E_PASSWORD=... npx playwright test
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    // Optional: point at an already-installed Chromium when the bundled revision is not available.
    launchOptions: process.env.E2E_CHROMIUM_PATH ? { executablePath: process.env.E2E_CHROMIUM_PATH } : {},
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:4173", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
