import { defineConfig, devices } from "@playwright/test";

// PlayDesk browser E2E — the integrity suite's UI layer.
//
// These tests drive a real browser against a LIVE docker compose stack
// (frontend on :3000, backend on :8000). Start it first:
//     docker compose up -d --build
//
// Files are named *.e2e.ts (not *.spec.ts) so the vitest unit runner does
// not collect them.

const BASE_URL = process.env.PLAYDESK_WEB ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  // Journeys share one backend; running them serially keeps state predictable.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL: BASE_URL,
    // Deliberately NOT the store timezone. The app must pin all display to
    // America/Toronto regardless of the viewer's clock — if that regresses,
    // the time-correctness test fails here instead of in a demo.
    timezoneId: "Asia/Tokyo",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
