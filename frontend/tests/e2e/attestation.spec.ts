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
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["contributor", "operator", "attestor", "admin"],
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

    if (path === "/v1/credentials" && request.method() === "GET") {
      await fulfillJson(route, {
        credentials: [
          {
            created_at: "2026-06-10T00:00:00Z",
            evidence_file_keys: [],
            expires_date: null,
            id: "00000000-0000-4000-8000-000000000041",
            issued_date: "2025-01-01",
            issuer: "Global Institute",
            title: "Certified Operating Model Lead",
            updated_at: "2026-06-10T00:00:00Z",
            user_id: "00000000-0000-4000-8000-000000000001",
          },
        ],
      });
      return;
    }

    if (path === "/v1/credentials" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, string>;
      await fulfillJson(route, {
        ...body,
        created_at: "2026-06-10T00:00:00Z",
        evidence_file_keys: [],
        expires_date: null,
        id: "00000000-0000-4000-8000-000000000042",
        updated_at: "2026-06-10T00:00:00Z",
        user_id: "00000000-0000-4000-8000-000000000001",
      }, 201);
      return;
    }

    if (path === "/v1/attestations" && request.method() === "GET") {
      await fulfillJson(route, {
        attestations: [
          {
            attestor_id: null,
            created_at: "2026-06-10T00:00:00Z",
            currency: "USD",
            escrow_id: null,
            fee_amount: "250.00",
            id: "00000000-0000-4000-8000-000000000050",
            outcome: null,
            requested_jurisdictions: ["US"],
            requested_specializations: ["governance"],
            requestor_id: "00000000-0000-4000-8000-000000000001",
            status: "matching",
            target_id: "00000000-0000-4000-8000-000000000060",
            target_type: "framework",
            updated_at: "2026-06-10T00:00:00Z",
          },
        ],
      });
      return;
    }

    if (path === "/v1/attestor/assignments") {
      await fulfillJson(route, {
        assignments: [
          {
            accepted_at: null,
            attestation_id: "00000000-0000-4000-8000-000000000050",
            attestation_status: "offered",
            cohort_index: 0,
            completion_due_at: null,
            expires_at: "2026-06-12T00:00:00Z",
            offer_id: "00000000-0000-4000-8000-000000000070",
            offer_status: "offered",
            requested_jurisdictions: ["US"],
            requested_specializations: ["governance"],
            target_id: "00000000-0000-4000-8000-000000000060",
            target_type: "framework",
          },
        ],
      });
      return;
    }

    if (path === "/v1/attestor/applications/mine") {
      await fulfillJson(route, {
        applications: [
          {
            id: "00000000-0000-4000-8000-000000000099",
            user_id: "00000000-0000-4000-8000-000000000001",
            status: "pending",
            specializations: ["isso"],
            jurisdictions: ["us"],
            credentials_summary: "huininkomo",
            sample_work: {},
            professional_references: "",
            admin_feedback: null,
            reviewed_by: null,
            reviewed_at: null,
            created_at: "2026-06-20T12:00:00Z",
          },
        ],
      });
      return;
    }

    if (path === "/v1/admin/attestor/applications") {
      await fulfillJson(route, {
        applications: [
          {
            id: "00000000-0000-4000-8000-000000000099",
            user_id: "00000000-0000-4000-8000-000000000001",
            status: "pending",
            specializations: ["isso"],
            jurisdictions: ["us"],
            credentials_summary: "huininkomo",
            sample_work: {},
            professional_references: "",
            admin_feedback: null,
            reviewed_by: null,
            reviewed_at: null,
            created_at: "2026-06-20T12:00:00Z",
          },
        ],
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked attestation route." }, 404);
  });
}

test("authenticated user can open Attestation workspaces", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      name: "session_hint",
      path: "/",
      value: sessionHintValue(),
    },
  ]);
  await mockAttestationApi(page);

  await page.goto("/settings/credentials");
  await expect(page.getByRole("heading", { name: "Professional credentials" })).toBeVisible();
  await expect(page.getByText("Certified Operating Model Lead")).toBeVisible();

  await page.goto("/attestations");
  await expect(page.getByRole("heading", { name: "Attestation requests" })).toBeVisible();
  await expect(page.getByText("$250")).toBeVisible();

  await page.goto("/attestor/assignments");
  await expect(page.getByRole("heading", { name: "Assignments" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept" })).toBeVisible();

  await page.goto("/attestor/applications");
  await expect(page.getByRole("heading", { name: "Attestor application" })).toBeVisible();

  await page.goto("/admin/attestations");
  await expect(page.getByRole("heading", { name: "Review and resolution" })).toBeVisible();
});
