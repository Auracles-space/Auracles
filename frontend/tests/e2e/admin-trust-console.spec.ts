/**
 * Browser-level checks for the admin trust console and step-up 2FA.
 *
 * Backend gating rules are covered by FastAPI tests. This spec proves the
 * frontend contract: the first sensitive action opens the global step-up
 * prompt, a second action inside the window does not, the attestor pipeline
 * lives on one page with tabs, and the disputes page tabs between queues.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md.
 */
import { createHmac } from "node:crypto";

import { type BrowserContext, expect, type Page, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

/**
 * Encode text as URL-safe base64 without padding.
 *
 * @param value - Raw value.
 */
function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create a signed admin session hint accepted by middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["admin"],
        totp_verified: true,
        user_id: "00000000-0000-4000-8000-000000000001",
      },
      ["exp", "iat", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret)
    .update(payload)
    .digest("base64url");
  return `${payload}.${signature}`;
}

/**
 * Fulfill mocked API responses with browser-accepted CORS headers.
 *
 * @param route - Playwright route object.
 * @param body - JSON payload.
 * @param status - HTTP status code.
 */
async function fulfillJson(
  route: Parameters<Parameters<Page["route"]>[1]>[0],
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    headers: {
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type,authorization",
      "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
      "access-control-allow-origin": appOrigin,
      "content-type": "application/json",
    },
    status,
  });
}

/**
 * Save a full-page screenshot when E2E_SHOTS names a directory.
 *
 * Off by default; used for visual review at desktop and phone widths
 * (E2E_VIEWPORT=375 shrinks the viewport first).
 */
async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.E2E_SHOTS;
  if (!dir) return;
  await page.screenshot({ fullPage: true, path: `${dir}/${name}.png` });
}

type TrustState = {
  /** Whether the mocked backend currently holds a step-up window. */
  stepUpActive: boolean;
  /** Organizations awaiting a business-verification verdict. */
  pendingOrgs: { id: string; name: string; legal_name: string }[];
  /** Attestor applications by status. */
  applications: Record<string, unknown>[];
  /** Codes accepted by the mocked step-up endpoint. */
  acceptedCode: string;
  /** Count of sensitive calls that were refused for lack of a window. */
  refusals: number;
  /** Capability status per organization, as the directory lists it. */
  capabilities: Record<string, Record<string, string>>;
  /** Stored admin reasons per organization and capability. */
  capabilityReasons: Record<string, Record<string, string>>;
};

/**
 * Install the mocked trust API with step-up gating on sensitive writes.
 *
 * @param page - Active Playwright page.
 * @param state - Mutable fixture state shared with the test body.
 */
async function mockTrustApi(page: Page, state: TrustState): Promise<void> {
  const org = (id: string, name: string, legalName: string) => ({
    capabilities: state.capabilities[id] ?? {},
    capability_reasons: state.capabilityReasons[id] ?? {},
    country: "NG",
    created_at: "2026-09-01T09:00:00Z",
    deactivated_at: null,
    id,
    kyb_status: "pending",
    kyb_submitted_at: "2026-09-02T09:00:00Z",
    legal_name: legalName,
    member_count: 3,
    name,
    registration_number: "RC-100200",
    slug: name.toLowerCase().replace(/\s+/g, "-"),
    suspended_at: null,
  });

  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/auth/step-up" && method === "GET") {
      await fulfillJson(route, {
        active: state.stepUpActive,
        verified_until: state.stepUpActive
          ? new Date(Date.now() + 600_000).toISOString()
          : null,
      });
      return;
    }
    if (path === "/v1/auth/step-up" && method === "POST") {
      const body = request.postDataJSON() as { code?: string };
      if (body.code !== state.acceptedCode) {
        await fulfillJson(route, { detail: "Invalid 2FA code." }, 422);
        return;
      }
      state.stepUpActive = true;
      await fulfillJson(route, {
        verified_until: new Date(Date.now() + 600_000).toISOString(),
      });
      return;
    }

    // Every sensitive write below refuses until the window is open.
    const capabilityMatch = path.match(
      /^\/v1\/admin\/orgs\/([^/]+)\/(contributor|operator|attestor)-capability\/(suspend|reinstate|revoke)$/,
    );
    const sensitive =
      (method === "POST" && /\/v1\/admin\/orgs\/[^/]+\/kyb\/review$/.test(path)) ||
      (method === "POST" && /\/v1\/admin\/org-attestor-applications\/[^/]+\/approve$/.test(path)) ||
      (method === "POST" && capabilityMatch !== null);
    if (sensitive && !state.stepUpActive) {
      state.refusals += 1;
      await fulfillJson(route, { detail: { error_code: "step_up_required" } }, 403);
      return;
    }

    if (path === "/v1/admin/orgs" && method === "GET") {
      const kyb = url.searchParams.get("kyb_status");
      const orgs = kyb === "pending"
        ? state.pendingOrgs.map((item) => org(item.id, item.name, item.legal_name))
        : state.pendingOrgs.map((item) => org(item.id, item.name, item.legal_name));
      await fulfillJson(route, { orgs, page: 1, page_size: 50, total: orgs.length });
      return;
    }
    if (capabilityMatch && method === "POST") {
      const [, orgId, capability, action] = capabilityMatch;
      const body = (request.postDataJSON() ?? {}) as { reason?: string };
      if (action !== "reinstate" && !body.reason) {
        await fulfillJson(route, { detail: "reason required" }, 422);
        return;
      }
      const next = action === "suspend" ? "suspended" : action === "revoke" ? "revoked" : "active";
      state.capabilities[orgId] = { ...(state.capabilities[orgId] ?? {}), [capability]: next };
      const reasons = { ...(state.capabilityReasons[orgId] ?? {}) };
      if (body.reason) {
        reasons[capability] = body.reason;
      } else {
        delete reasons[capability];
      }
      state.capabilityReasons[orgId] = reasons;
      await fulfillJson(route, {}, 204);
      return;
    }
    const kybMatch = path.match(/^\/v1\/admin\/orgs\/([^/]+)\/kyb\/review$/);
    if (kybMatch && method === "POST") {
      state.pendingOrgs = state.pendingOrgs.filter((item) => item.id !== kybMatch[1]);
      await fulfillJson(route, { org_id: kybMatch[1], kyb_status: "verified" });
      return;
    }

    if (path === "/v1/admin/org-attestor-applications" && method === "GET") {
      const status = url.searchParams.get("status");
      const applications = state.applications.filter((app) =>
        status === "trial" ? app.trial_status !== null : app.status === status,
      );
      await fulfillJson(route, { applications, page: 1, page_size: 10, total: applications.length });
      return;
    }
    const approveMatch = path.match(/^\/v1\/admin\/org-attestor-applications\/([^/]+)\/approve$/);
    if (approveMatch && method === "POST") {
      state.applications = state.applications.map((app) =>
        app.id === approveMatch[1] ? { ...app, status: "approved", capability_status: "active" } : app,
      );
      await fulfillJson(route, { id: approveMatch[1], status: "approved" });
      return;
    }
    const docsMatch = path.match(/^\/v1\/admin\/org-attestor-applications\/[^/]+\/documents$/);
    if (docsMatch && method === "GET") {
      await fulfillJson(route, { documents: [] });
      return;
    }
    if (path === "/v1/admin/org-attestor-applications/calibration-fixtures" && method === "GET") {
      await fulfillJson(route, { fixtures: [] });
      return;
    }

    if (path === "/v1/admin/attestations" && method === "GET") {
      await fulfillJson(route, { attestations: [] });
      return;
    }
    if (path === "/v1/attestor-orgs" && method === "GET") {
      await fulfillJson(route, { attestors: [] });
      return;
    }
    if (path === "/v1/admin/attestation-disputes" && method === "GET") {
      await fulfillJson(route, {
        disputes: [
          {
            id: "dispute-1",
            attestation_id: "att-1",
            attestor_org_name: "Lagos Assurance",
            category: "scope_error",
            reason: "The report reviewed the wrong version.",
            status: "open",
            outcome: null,
            is_complex: false,
            resolution_due_at: new Date(Date.now() + 86_400_000).toISOString(),
            resolved_at: null,
            review_type: "quality",
            fee_amount: "500.00",
            currency: "NGN",
            created_at: "2026-09-10T09:00:00Z",
          },
        ],
      });
      return;
    }
    if (path === "/v1/admin/projects/disputes" && method === "GET") {
      await fulfillJson(route, { disputes: [] });
      return;
    }

    await fulfillJson(route, { detail: `Unmocked ${method} ${path}` }, 404);
  });
}

/**
 * Sign the admin in and install the mocked API.
 *
 * @param page - Active page.
 * @param context - Browser context receiving the session-hint cookie.
 * @param state - Fixture state.
 */
async function signInAsAdmin(
  page: Page,
  context: BrowserContext,
  state: TrustState,
): Promise<void> {
  const width = Number(process.env.E2E_VIEWPORT ?? 0);
  if (width > 0) {
    await page.setViewportSize({ height: 900, width });
  }
  await context.addCookies([
    { domain: "127.0.0.1", name: "session_hint", path: "/", value: sessionHintValue() },
  ]);
  await mockTrustApi(page, state);
  await mockSessionBootstrap(page, {
    displayName: "Admin User",
    email: "admin@example.com",
    roles: ["admin"],
  });
}

function freshState(): TrustState {
  return {
    acceptedCode: "123456",
    applications: [
      {
        id: "app-1",
        org_id: "org-9",
        org_name: "Lagos Assurance",
        status: "submitted",
        kyb_status: "verified",
        trial_status: "passed",
        capability_status: null,
        admin_feedback: null,
        created_at: "2026-09-05T09:00:00Z",
        reviewed_at: null,
      },
    ],
    pendingOrgs: [
      { id: "org-1", name: "Kano Audit", legal_name: "Kano Audit Partners Ltd" },
      { id: "org-2", name: "Abuja Compliance", legal_name: "Abuja Compliance Ltd" },
    ],
    refusals: 0,
    stepUpActive: false,
    capabilities: { "org-1": { contributor: "active", operator: "active" } },
    capabilityReasons: {},
  };
}

test("the first KYB verdict prompts for a code; the second inside the window does not", async ({
  context,
  page,
}) => {
  const state = freshState();
  await signInAsAdmin(page, context, state);

  await page.goto("/admin/organizations");
  await expect(page.getByRole("heading", { name: /Kano Audit Partners Ltd/ })).toBeVisible();

  await page.getByRole("button", { name: "Verify organization" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Confirm it's you");
  await dialog.getByLabel("Authenticator code").fill("123456");
  await dialog.getByRole("button", { name: "Verify" }).click();

  await expect(page.getByText("Organization verified. Its capabilities can now be activated.")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Kano Audit Partners Ltd/ })).toHaveCount(0);
  await expect(page.getByText(/Verified · \d+ min/)).toBeVisible();

  await page.getByRole("button", { name: "Verify organization" }).first().click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Abuja Compliance Ltd/ })).toHaveCount(0);
  expect(state.refusals).toBe(1);
});

test("an admin suspends one capability from the directory with an owner-visible reason", async ({
  context,
  page,
}) => {
  const state = freshState();
  await signInAsAdmin(page, context, state);

  await page.goto("/admin/organizations");
  const row = page.getByRole("row", { name: /Kano Audit/ });
  await expect(row.getByText("Contributor active")).toBeVisible();
  await row.getByRole("button", { name: "Capabilities" }).click();

  const capabilities = page.getByRole("dialog", { name: "Kano Audit" });
  await expect(capabilities.getByRole("heading", { name: "Contributor" })).toBeVisible();
  await expect(capabilities.getByText("Not active")).toBeVisible();
  await shot(page, "admin-org-capabilities");

  // The contributor section is first; its Suspend opens the confirm step.
  await capabilities.getByRole("button", { name: "Suspend" }).first().click();
  const confirm = page.getByRole("dialog").filter({ hasText: "Suspend contributor capability?" });
  await confirm.getByLabel(/Reason/).fill("Framework artifacts failed the malware scan twice.");
  await shot(page, "admin-org-capability-confirm");
  await confirm.getByRole("button", { name: "Suspend" }).click();

  // No step-up window yet: the global prompt takes over, then the write retries.
  const stepUp = page.getByRole("dialog").filter({ hasText: "Confirm it's you" });
  await stepUp.getByLabel("Authenticator code").fill("123456");
  await stepUp.getByRole("button", { name: "Verify" }).click();

  await expect(capabilities.getByText("Framework artifacts failed the malware scan twice.")).toBeVisible();
  await expect(capabilities.getByRole("button", { name: "Reinstate" }).first()).toBeEnabled();
  await shot(page, "admin-org-capability-suspended");
  await capabilities.getByRole("button", { name: "Close" }).click();
  await expect(row.getByText("Contributor suspended")).toBeVisible();
  await shot(page, "admin-org-directory");
  expect(state.refusals).toBe(1);
});

test("the attestor console approves an application from one page with tabs", async ({
  context,
  page,
}) => {
  const state = freshState();
  await signInAsAdmin(page, context, state);

  await page.goto("/admin/org-attestors");
  await expect(page).toHaveURL(/\/admin\/attestors\?tab=applications/);
  await expect(page.getByRole("heading", { name: "Attestor organizations" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Applications/ })).toHaveAttribute("aria-selected", "true");

  await page.getByRole("button", { name: /Lagos Assurance/ }).click();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Authenticator code").fill("123456");
  await dialog.getByRole("button", { name: "Verify" }).click();

  await expect(page.getByText("Application approved. Attestor capability is active.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Suspend", exact: true })).toBeEnabled();

  await page.getByRole("tab", { name: "Fixtures" }).click();
  await expect(page).toHaveURL(/tab=fixtures/);
  await expect(page.getByRole("heading", { name: "Calibration Fixtures" })).toBeVisible();
});

test("disputes tab between Attestation and Project queues", async ({ context, page }) => {
  const state = freshState();
  await signInAsAdmin(page, context, state);

  await page.goto("/admin/disputes");
  await expect(page.getByRole("heading", { level: 1, name: "Disputes" })).toBeVisible();
  await expect(page.getByText("The report reviewed the wrong version.")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Attestation/ })).toContainText("1");

  await page.getByRole("tab", { name: /Project/ }).click();
  await expect(page).toHaveURL(/tab=project/);
  await expect(page.getByText("The report reviewed the wrong version.")).toHaveCount(0);
});
