/**
 * Browser-level Organization Operator flow.
 *
 * Covers the Org Projects tab. Creation and invitations are covered by
 * organizations.spec.ts against the current UI: this file used to repeat them
 * through a `/dashboard/organizations/new` route that no longer exists, a
 * slug-based org URL, an Invitations tab an unverified org does not show, and
 * an `auracles_access_token` in localStorage that the app never reads.
 */
import { createHmac } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const orgId = "00000000-0000-4000-8000-0000000000a1";
const currentUserId = "00000000-0000-4000-8000-000000000011";

function base64Url(value: string): string {
  return Buffer.from(value).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}


function sessionHintValue(roles = ["operator"]): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles,
        totp_verified: true,
        user_id: currentUserId,
      },
      ["exp", "iat", "roles", "totp_verified", "user_id"]
    )
  );
  const signature = createHmac("sha256", sessionHintSecret).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

async function fulfillJson(route: Parameters<Parameters<Page["route"]>[1]>[0], body: unknown, status = 200): Promise<void> {
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

async function mockOrgApi(page: Page): Promise<void> {
  // Seeded rather than left null: this file no longer creates the org through
  // the UI (organizations.spec.ts owns that), so the detail read has to answer
  // from the first request or the page renders its error state.
  let createdOrg: unknown = {
    country: "NG",
    created_at: "2026-06-01T00:00:00Z",
    id: orgId,
    kyb_status: "verified",
    name: "Test Org",
    slug: "test-org",
    status: "active",
    updated_at: "2026-06-01T00:00:00Z",
  };
  const invites: unknown[] = [];

  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/auth/me") {
      await fulfillJson(route, {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Test User",
        email: "test@example.com",
        email_verified: true,
        id: currentUserId,
        kyc_status: "verified",
        roles: ["operator"],
      });
      return;
    }

    // The organization shell resolves the current org from /v1/orgs/mine, not
    // from the detail read — a nested membership record, not a bare org.
    if (path === "/v1/orgs/mine") {
      await fulfillJson(route, {
        organizations: [
          {
            capabilities: { operator: "active" },
            capability_reasons: {},
            counts: { members: 1 },
            grants: {},
            kyb_status: "verified",
            kyb_verified_at: "2026-06-01T00:00:00Z",
            org: createdOrg,
            role: "owner",
          },
        ],
      });
      return;
    }

    if (path === "/v1/orgs") {
      if (request.method() === "POST") {
        const body = JSON.parse(request.postData() ?? "{}");
        createdOrg = {
          id: orgId,
          name: body.name,
          slug: body.slug,
          status: "active",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        await fulfillJson(route, createdOrg, 201);
        return;
      }
      if (request.method() === "GET") {
        await fulfillJson(route, { organizations: createdOrg ? [createdOrg] : [] });
        return;
      }
    }

    if (path === `/v1/orgs/${orgId}`) {
      await fulfillJson(route, createdOrg);
      return;
    }

    if (path === `/v1/orgs/${orgId}/invitations`) {
      if (request.method() === "POST") {
        const body = JSON.parse(request.postData() ?? "{}");
        const invite = {
          id: "invite-1",
          email: body.email,
          role: body.role,
          status: "pending",
          created_at: new Date().toISOString(),
          expires_at: new Date().toISOString(),
        };
        invites.push(invite);
        await fulfillJson(route, invite, 201);
        return;
      }
      if (request.method() === "GET") {
        await fulfillJson(route, { invitations: invites });
        return;
      }
    }

    if (path === `/v1/orgs/${orgId}/projects`) {
      await fulfillJson(route, {
        projects: [
          {
            id: "proj-1",
            title: "Org Playbook",
            description: "Org description",
            status: "open",
            operator_name: "Test User",
            budget_min: "100",
            budget_max: "200",
            category: "operations",
            milestone_plan_status: "draft",
          },
        ],
      });
      return;
    }

    // Anything not handled above would otherwise reach a backend that is not
    // running here, and the rejection surfaces as an error page rather than as
    // the assertion that actually failed.
    await fulfillJson(route, {});
  });
  await mockSessionBootstrap(page);
}

test.describe("Org Operator Flow", () => {
  test.beforeEach(async ({ context }) => {
    await context.addCookies([
      {
        domain: "127.0.0.1",
        httpOnly: false,
        name: "session_hint",
        path: "/",
        sameSite: "Lax",
        value: sessionHintValue(),
      },
    ]);
  });

  test("an owner sees their organization's projects", async ({ page }) => {
    await mockOrgApi(page);

    await page.goto(`${appOrigin}/dashboard/organizations/${orgId}/projects`);

    await expect(page.getByText("Org Playbook")).toBeVisible();
    await expect(page.getByText("Org description")).toBeVisible();
  });
});
