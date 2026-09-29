/**
 * Playwright configuration for frontend browser flows.
 *
 * The auth e2e suite mocks backend responses at the network boundary so the
 * UI contract can be verified before staging-only backend test hooks exist.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  expect: {
    // 5s was enough locally and not on a CI runner: the suite runs against
    // `next dev`, which compiles a route the first time it is hit, and the
    // project workspace took longer than that to appear on a 4-vCPU box. The
    // test timeout does not cover this — `expect` carries its own.
    timeout: 15_000,
  },
  testDir: "./tests/e2e",
  timeout: 60_000,
  // A first-hit compile stall is a slow pass, not a failure, so CI retries it
  // rather than failing the branch. This also makes `trace: "on-first-retry"`
  // below mean something: with retries at their default of 0 no trace was ever
  // captured, so the one CI failure so far left nothing to look at.
  retries: process.env.CI ? 2 : 0,
  // Pinned rather than left to Playwright's "50% of cores" default. The suite
  // runs against `next dev`, which compiles each route on first hit, so more
  // workers than this put several uncompiled routes under load at once and
  // tests that pass in seconds time out after minutes. Two is what a 4-vCPU
  // runner would pick anyway; fixing it keeps a developer's larger machine
  // from behaving differently from CI.
  workers: 2,
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  webServer: {
    command:
      "SESSION_HINT_SECRET=auracles-e2e-secret NEXT_PUBLIC_WAITLIST_MODE=false NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_auracles_e2e corepack pnpm dev --hostname 127.0.0.1 --port 3100",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    url: "http://127.0.0.1:3100",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
