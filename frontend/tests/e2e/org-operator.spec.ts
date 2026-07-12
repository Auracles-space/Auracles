/**
 * Browser-level Organization Operator flow.
 *
 * Verifies org creation, invitation sending, and viewing the Org Projects tab.
 */
import { createHmac } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const orgId = "00000000-0000-4000-8000-000000000org";
const currentUserId = "00000000-0000-4000-8000-000000000011";

function base64Url(value: string): string {
  return Buffer.from(value).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fakeAccessToken(roles: string[]): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      exp: Math.floor(Date.now() / 1000) + 900,
      roles,
      sub: currentUserId,
      totp_verified: true,
    })
  );
  return `${header}.${payload}.signature`;
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
  let createdOrg: unknown = null;
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

    if (path === "/v1/organizations") {
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

    if (path === `/v1/organizations/${orgId}`) {
      await fulfillJson(route, createdOrg);
      return;
    }

    if (path === `/v1/organizations/${orgId}/invitations`) {
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

    if (path === `/v1/organizations/${orgId}/projects`) {
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

    await route.continue();
  });
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

  test("creates org, sends invite, views projects", async ({ page }) => {
    await mockOrgApi(page);

    // Provide the JWT inside localStorage so form-client can use it
    await page.goto(appOrigin);
    await page.evaluate((token) => {
      localStorage.setItem("auracles_access_token", token);
    }, fakeAccessToken(["operator"]));

    // 1. Create org
    await page.goto(`${appOrigin}/dashboard/organizations/new`);
    await page.waitForLoadState("networkidle");
    await page.fill('input[name="name"]', "Test Org");
    await page.fill('input[name="slug"]', "test-org");
    await page.click('button[type="submit"]');

    // 2. View org and send invite
    await expect(page).toHaveURL(`${appOrigin}/dashboard/organizations/test-org`);
    await page.click("text=Invitations");
    
    // Fill invite form
    await page.fill('input[name="email"]', "test@example.com");
    // select role
    await page.selectOption('select[name="role"]', "member");
    await page.click('button:has-text("Send Invitation")');
    await expect(page.getByText("test@example.com")).toBeVisible();

    // 3. View org projects
    await page.click("text=Projects");
    await expect(page).toHaveURL(`${appOrigin}/dashboard/organizations/test-org/projects`);
    await expect(page.getByText("Org Playbook")).toBeVisible();
    await expect(page.getByText("Org description")).toBeVisible();
  });
});
