/**
 * Browser-level Attestation workspace checks for Slice 12.
 *
 * Backend lifecycle, escrow, matching, and dispute rules stay covered by
 * FastAPI tests. This spec proves the authenticated frontend pages call the
 * generated API surface and render the main workflow states.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

/**
 * Convert text into base64url encoding.
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
 * Create a signed session hint accepted by middleware.
 */
function sessionHintCookie(roles: string[]): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        roles,
        totp_verified: true,
        user_id: "00000000-0000-4000-8000-000000000001",
      },
      ["exp", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret)
    .update(payload)
    .digest("base64url");
  return `session_hint=${payload}.${signature}; Path=/; HttpOnly; SameSite=Lax`;
}

function sessionHintValue(): string {
  return sessionHintCookie([
    "contributor",
    "operator",
    "attestor",
    "admin",
    "platform_admin",
  ])
    .replace("session_hint=", "")
    .split(";")[0] ?? "";
}

/**
 * Create an unsigned JWT-shaped token for frontend role-routing tests.
 *
 * @param roles - Roles to encode in the public JWT payload.
 */
function fakeAccessToken(roles: string[]): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles,
        totp_verified: true,
        user_id: "00000000-0000-4000-8000-000000000001",
      },
      ["exp", "iat", "roles", "totp_verified", "user_id"],
    ),
  );
  return `${header}.${payload}.`;
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
 * Install mocked Attestation API routes.
 *
 * @param page - Active Playwright page.
 */
async function mockAttestationApi(page: Page): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken([
          "contributor",
          "operator",
          "attestor",
          "admin",
          "platform_admin",
        ]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/users/me") {
      await fulfillJson(route, {
        id: "00000000-0000-4000-8000-000000000001",
        email: "test@example.com",
        display_name: "Test User",
        email_verified: true,
        kyc_status: "verified",
        roles: ["contributor", "operator", "attestor", "admin", "platform_admin"],
      });
      return;
    }

    if (path === "/v1/orgs/mine") {
      await fulfillJson(route, {
        organizations: [
          {
            org: {
              id: "org-1",
              name: "Audit Ltd",
              slug: "audit-ltd",
              created_at: "2026-06-20T12:00:00Z",
              logo_url: null,
              description: "Audit Ltd"
            },
            role: "owner",
            capabilities: { "attestor": "active" },
            // The shell hides every capability tab until the business is
            // verified (DESIGN-1), so the mock must say so.
            kyb_status: "verified"
          }
        ]
      });
      return;
    }


    if (path === "/v1/orgs/org-1") {
      await fulfillJson(route, {
        id: "org-1",
        name: "Audit Ltd",
        slug: "audit-ltd",
        role: "owner"
      });
      return;
    }

    if (path === "/v1/orgs/org-1/attestor-application") {
      await fulfillJson(route, {
        id: "app-1",
        org_id: "org-1",
        status: "pending",
        nda_signed_at: null,
        kyb_verified_at: null,
        tax_document_verified_at: null,
        financial_onboarding_completed_at: null,
        trial_member_id: null,
        trial_attestation_id: null,
        trial_completed_at: null,
        created_at: "2026-06-20T12:00:00Z",
      });
      return;
    }

    if (path === "/v1/admin/org-attestor-applications") {
      await fulfillJson(route, {
        applications: [
          {
            id: "app-1",
            org_id: "org-1",
            org_name: "Audit Ltd",
            legal_name: "Audit Ltd",
            status: "pending",
            nda_signed_at: "2026-06-20T12:00:00Z",
            kyb_verified_at: null,
            tax_document_verified_at: null,
            financial_onboarding_completed_at: null,
            created_at: "2026-06-20T12:00:00Z",
          },
        ],
      });
      return;
    }

    if (path === "/v1/orgs/org-1/attestation-offers") {
      await fulfillJson(route, {
        offers: [
          {
            offer_id: "offer-1",
            attestation_id: "att-1",
            target_type: "framework",
            target_id: "fw-1",
            status: "offered",
            cohort_index: 0,
            match_score: 95,
            offered_at: "2026-06-20T12:00:00Z",
            expires_at: "2026-06-22T12:00:00Z",
          },
        ],
      });
      return;
    }

    if (path === "/v1/orgs/org-1/attestations") {
      await fulfillJson(route, { attestations: [], total: 0, page: 1, page_size: 50 });
      return;
    }

    if (path === "/v1/orgs/org-1/members") {
      await fulfillJson(route, {
        members: [
          { id: "mem-1", user_id: "user-1", role: "owner", name: "Alice Owner" }
        ]
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked attestation route." }, 404);
  });
}

test("authenticated user can open Org Attestation workspaces", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      sameSite: "Lax",
      secure: false,
      name: "session_hint",
      path: "/",
      value: sessionHintValue(),
    },
  ]);
  await mockAttestationApi(page);

  await page.goto("/dashboard/organizations");
  await expect(page.getByRole("heading", { name: "Organizations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Ltd" })).toBeVisible();

  // An approved attestor's tab opens on its work, not the finished application.
  await page.goto("/dashboard/organizations/org-1/attestor");
  await expect(page).toHaveURL(/\/attestor\/(offers|queue)$/);

  await page.goto("/admin/org-attestors");
  await expect(page).toHaveURL(/\/admin\/attestors/);
  await expect(page.getByRole("heading", { name: "Attestor organizations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Ltd" })).toBeVisible();

  await page.goto("/dashboard/organizations/org-1/attestor/queue");
  await expect(page.getByText("Offers")).toBeVisible();
});
