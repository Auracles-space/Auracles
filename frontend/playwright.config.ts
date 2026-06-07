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
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  webServer: {
    command:
      "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 corepack pnpm dev --hostname 127.0.0.1 --port 3100",
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
