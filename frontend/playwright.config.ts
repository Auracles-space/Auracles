/**
 * Playwright configuration for frontend browser flows.
 *
 * The auth e2e suite mocks backend responses at the network boundary so the
 * UI contract can be verified before staging-only backend test hooks exist.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  expect: {
    timeout: 5_000,
  },
  testDir: "./tests/e2e",
  timeout: 30_000,
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
