/**
 * Browser-level checks for the organization owner's onboarding journey.
 *
 * Backend rules stay covered by FastAPI tests. This spec proves the owner
 * surfaces render the states an administrator puts an organization in
 * (in review, suspended with a reason, capability revoked) and that the
 * invitation inbox and the rejected-application path work end to end.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const userId = "00000000-0000-4000-8000-000000000001";

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        roles: ["contributor"],
        totp_verified: true,
        user_id: userId,
      },
      ["exp", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret)
    .update(payload)
    .digest("base64url");
  return `${payload}.${signature}`;
}

function fakeAccessToken(): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["contributor"],
        totp_verified: true,
        user_id: userId,
      },
      ["exp", "iat", "roles", "totp_verified", "user_id"],
    ),
  );
  return `${header}.${payload}.`;
}

async function fulfillJson(
  route: Parameters<Parameters<Page["route"]>[1]>[0],
  body: unknown,
  status = 200,
): Promise<void> {
  await route.fulfill({
    body: status === 204 ? "" : JSON.stringify(body),
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

/** Mutable server state the mocks read so actions change what renders. */
type OwnerState = {
  invitations: Array<Record<string, unknown>>;
  applicationStatus: "rejected" | "draft";
  applicationCreated: boolean;
};

function org(id: string, name: string, overrides: Record<string, unknown> = {}) {
  // `org` overrides merge into the nested org object; everything else is
  // top-level entry state.
  const { org: orgOverrides, ...entryOverrides } = overrides;
  return {
    org: {
      id,
      name,
      slug: id,
      country: "NG",
      logo_key: null,
      logo_url: null,
      website: null,
      description: null,
      created_at: "2026-06-20T12:00:00Z",
      suspended_at: null,
      suspension_reason: null,
      ...((orgOverrides as Record<string, unknown>) ?? {}),
    },
    role: "owner",
    capabilities: {},
    capability_reasons: {},
    kyb_status: "verified",
    grants: {},
    nda_required: false,
    counts: { offers: 0, queue: 0, invitations: 0 },
    ...entryOverrides,
  };
}

const organizations = [
  org("org-review", "Lagos Audit Partners", { kyb_status: "pending" }),
  org("org-suspended", "Meridian Advisory", {
    org: {
      suspended_at: "2026-09-13T10:00:00Z",
      suspension_reason: "Repeated chargebacks on operator purchases.",
    },
  }),
  org("org-revoked", "Harbour Attestations", {
    capabilities: { attestor: "revoked", contributor: "active" },
    capability_reasons: { attestor: "Calibration drift after two disputes." },
    nda_required: true,
  }),
];

function application(state: OwnerState) {
  return {
    id: state.applicationStatus === "draft" ? "app-2" : "app-1",
    org_id: "org-revoked",
    status: state.applicationStatus,
    sectors: ["finance"],
    functions: ["audit"],
    jurisdictions: ["NG"],
    credentials_summary: "ICAN-registered audit practice.",
    sample_work: {},
    professional_references: "Two references on file.",
    coi_declarations: [],
    coi_signed_at: null,
    coi_expires_at: null,
    confidentiality_signed_at: null,
    payout_account_id: null,
    tax_document_type: null,
    tax_document_key: null,
    trial_member_id: null,
    trial_attestation_id: null,
    admin_feedback:
      state.applicationStatus === "rejected"
        ? "The sample work did not show a completed engagement."
        : null,
    reviewed_at: state.applicationStatus === "rejected" ? "2026-09-01T09:00:00Z" : null,
    created_at: "2026-08-20T12:00:00Z",
    gate_checklist: {
      credentials_reviewed: false,
      undertakings_signed: false,
      tax_document_uploaded: false,
      payout_account_linked: false,
      trial_passed: false,
    },
    trial_status: null,
    trial_feedback: null,
  };
}

async function mockOwnerApi(page: Page, state: OwnerState): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }
    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }
    if (path === "/v1/users/me") {
      await fulfillJson(route, {
        id: userId,
        email: "owner@example.com",
        display_name: "Owner",
        email_verified: true,
        kyc_status: "verified",
        roles: ["contributor"],
      });
      return;
    }
    if (path === "/v1/notifications") {
      await fulfillJson(route, { notifications: [], unread_count: 0, total: 0 });
      return;
    }
    if (path === "/v1/orgs/mine") {
      await fulfillJson(route, { organizations });
      return;
    }
    if (path === "/v1/org-invitations/received") {
      await fulfillJson(route, { invitations: state.invitations });
      return;
    }
    const accept = path.match(/^\/v1\/org-invitations\/received\/([^/]+)\/accept$/);
    if (accept && method === "POST") {
      state.invitations = state.invitations.filter((item) => item.id !== accept[1]);
      await fulfillJson(route, { role: "member" });
      return;
    }
    if (path.endsWith("/nda")) {
      await fulfillJson(route, {
        required: false,
        current_version: "1.0",
        signed_version: null,
        signed_at: null,
      });
      return;
    }
    if (path === "/v1/orgs/org-revoked/attestor-application") {
      if (method === "POST") {
        state.applicationCreated = true;
        state.applicationStatus = "draft";
        await fulfillJson(route, application(state), 201);
        return;
      }
      await fulfillJson(route, application(state));
      return;
    }
    if (path === "/v1/orgs/org-revoked/members") {
      await fulfillJson(route, { members: [] });
      return;
    }
    await fulfillJson(route, { detail: `Unhandled mocked route ${method} ${path}` }, 404);
  });
}

async function signIn(context: Parameters<Parameters<typeof test>[2]>[0]["context"]) {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      name: "session_hint",
      path: "/",
      sameSite: "Lax",
      secure: false,
      value: sessionHintValue(),
    },
  ]);
}

function freshState(): OwnerState {
  return {
    invitations: [
      {
        created_at: "2026-09-13T00:00:00Z",
        id: "inv-1",
        invited_by_name: "Ada",
        org: { id: "org-new", logo_url: null, name: "Invited Org", slug: "invited-org" },
        role: "member",
      },
    ],
    applicationStatus: "rejected",
    applicationCreated: false,
  };
}

test("the list shows verification, suspension, and capability state, and resolves invitations", async ({
  context,
  page,
}) => {
  const state = freshState();
  await signIn(context);
  await mockOwnerApi(page, state);

  await page.goto("/dashboard/organizations");
  await expect(page.getByRole("heading", { name: "Organizations", level: 1 })).toBeVisible();

  // Inbox above the list.
  await expect(page.getByRole("heading", { name: "Invitations" })).toBeVisible();
  await expect(page.getByText("Invited Org")).toBeVisible();

  // Each state is visible on its card.
  const review = page.locator("a", { hasText: "Lagos Audit Partners" });
  await expect(review.getByText("In review")).toBeVisible();
  const suspended = page.locator("a", { hasText: "Meridian Advisory" });
  await expect(suspended.getByText("Suspended")).toBeVisible();
  const revoked = page.locator("a", { hasText: "Harbour Attestations" });
  await expect(revoked.getByText("Revoked")).toBeVisible();
  await expect(revoked.getByText("Attestor")).toBeVisible();

  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page).toHaveURL(/\/dashboard\/organizations\/org-new/);
  expect(state.invitations).toHaveLength(0);
});

test("the suspended organization's shell explains why and when", async ({ context, page }) => {
  await signIn(context);
  await mockOwnerApi(page, freshState());

  await page.goto("/dashboard/organizations/org-suspended");

  await expect(page.getByText("Organization suspended")).toBeVisible();
  await expect(page.getByText("Repeated chargebacks on operator purchases.")).toBeVisible();
  await expect(page.getByText(/13 Sept? 2026/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Contact support" })).toHaveAttribute(
    "href",
    /^mailto:/,
  );
});

test("a revoked capability is explained and a rejected application can be restarted", async ({
  context,
  page,
}) => {
  const state = freshState();
  await signIn(context);
  await mockOwnerApi(page, state);

  await page.goto("/dashboard/organizations/org-revoked/attestor");

  await expect(page.getByText("Attestor capability revoked")).toBeVisible();
  await expect(page.getByText("Calibration drift after two disputes.").first()).toBeVisible();

  await expect(page.getByText("Rejected").first()).toBeVisible();
  await expect(
    page.getByText("The sample work did not show a completed engagement."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Start a new application" }).click();
  await expect.poll(() => state.applicationCreated).toBe(true);
  await expect(page.getByText("Draft").first()).toBeVisible();
});
