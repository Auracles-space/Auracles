/**
 * Browser-level checks for the become-attestor front door.
 *
 * This suite mocks the browser-facing auth and organization endpoints, then
 * verifies that a user with no organizations can enter from the public
 * attestors page, create an organization, and land on the attestor checklist.
 */
import { createHmac } from "node:crypto";

import { expect, type BrowserContext, type Page, test } from "@playwright/test";

const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const userId = "00000000-0000-4000-8000-000000000001";

type MockOrganization = {
  capabilities: Record<string, string>;
  org: {
    country: string;
    id: string;
    name: string;
    slug: string;
  };
  role: string;
};

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create an unsigned JWT-shaped token for frontend routing tests.
 *
 * @param roles - Roles to encode in the public payload.
 */
function fakeAccessToken(roles: string[]): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      exp: Math.floor(Date.now() / 1000) + 900,
      roles,
      sub: userId,
      totp_verified: true,
    }),
  );
  return `${header}.${payload}.signature`;
}

/**
 * Create a signed session-hint cookie accepted by frontend middleware.
 *
 * @param roles - Roles encoded into the routing hint.
 */
function sessionHintCookie(roles: string[]): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles,
        totp_verified: true,
        user_id: userId,
      },
      ["exp", "iat", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret)
    .update(payload)
    .digest("base64url");
  return `session_hint=${payload}.${signature}; Path=/; SameSite=Lax`;
}

/**
 * Seed the browser with a verified authenticated session hint.
 *
 * @param context - Active Playwright browser context.
 * @param roles - Roles to encode in the session hint.
 */
async function seedSessionHint(
  context: BrowserContext,
  roles: string[],
): Promise<void> {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      name: "session_hint",
      path: "/",
      sameSite: "Lax",
      secure: false,
      value: sessionHintCookie(roles).replace("session_hint=", "").split(";")[0] ?? "",
    },
  ]);
}

/**
 * Fulfill mocked API responses with CORS headers accepted by the browser.
 *
 * @param route - Playwright route object.
 * @param body - JSON response payload.
 * @param status - HTTP status code.
 * @param headers - Extra response headers.
 */
async function fulfillJson(
  route: Parameters<Parameters<Page["route"]>[1]>[0],
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    headers: {
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type,authorization",
      "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
      "access-control-allow-origin": appOrigin,
      "content-type": "application/json",
      ...headers,
    },
    status,
  });
}

/**
 * Install the minimal mocked backend routes for the front-door flow.
 *
 * @param page - Active Playwright page.
 */
async function mockBecomeAttestorApi(page: Page): Promise<void> {
  const roles = ["contributor"];
  let organizations: MockOrganization[] = [];
  let createdCount = 0;
  const authRefreshRoute = new RegExp("^https?://[^/]+/v1/auth/refresh$");
  const authMeRoute = new RegExp("^https?://[^/]+/v1/auth/me$");
  const notificationsRoute = new RegExp("^https?://[^/]+/v1/notifications(?:\\?.*)?$");
  const orgsRoute = new RegExp("^https?://[^/]+/v1/orgs(?:/.*)?$");

  await page.route(authRefreshRoute, async (route) => {
    await fulfillJson(route, {
      access_token: fakeAccessToken(roles),
      expires_in: 900,
      token_type: "bearer",
    });
  });

  await page.route(authMeRoute, async (route) => {
    await fulfillJson(route, {
      avatar_url: null,
      deactivated_at: null,
      display_name: "Ada Markets",
      email: "ada@example.com",
      email_verified: true,
      id: userId,
      kyc_status: "unverified",
      roles,
    });
  });

  await page.route(notificationsRoute, async (route) => {
    await fulfillJson(route, {
      notifications: [],
      page: 1,
      page_size: 20,
      total: 0,
      unread_count: 0,
    });
  });

  await page.route(orgsRoute, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (pathname === "/v1/orgs/mine") {
      await fulfillJson(route, { organizations });
      return;
    }

    if (pathname === "/v1/orgs") {
      if (request.method() !== "POST") {
        await fulfillJson(route, { detail: "Unhandled org route." }, 405);
        return;
      }

      const body = request.postDataJSON() as {
        country?: string;
        name?: string;
        slug?: string;
      };
      createdCount += 1;
      const id = `org-${createdCount}`;

      organizations = [
        {
          capabilities: {},
          org: {
            country: body.country ?? "US",
            id,
            name: body.name ?? "Created Org",
            slug: body.slug ?? `created-${createdCount}`,
          },
          role: "owner",
        },
      ];

      await fulfillJson(route, {
        country: organizations[0].org.country,
        id,
        name: organizations[0].org.name,
        slug: organizations[0].org.slug,
      });
      return;
    }

    if (/^\/v1\/orgs\/[^/]+\/attestor-application$/.test(pathname)) {
      await fulfillJson(
        route,
        { detail: "Org attestor application not found.", status: 404 },
        404,
      );
      return;
    }

    await fulfillJson(route, { detail: "Unhandled org route." }, 404);
  });
}

test.describe("Become an attestor front door", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("a user with no org creates one and lands on the attestor checklist", async ({
    context,
    page,
  }) => {
    await seedSessionHint(context, ["contributor"]);
    await mockBecomeAttestorApi(page);

    await page.goto("/attestors");
    await page.locator('a[href="/dashboard/organizations/become-attestor"]').click();

    await expect(page.getByRole("dialog")).toBeVisible();

    const suffix = Date.now();
    await page.getByLabel(/Organization Name/i).fill("E2E Attestor Org");
    await page.getByLabel(/Slug/i).fill(`e2e-attestor-${suffix}`);
    await page.getByRole("button", { name: /^Create Organization$/i }).click();

    await expect(page).toHaveURL(/\/dashboard\/organizations\/org-1\/attestor$/);
    await expect(page.getByText(/Attestor Application/i)).toBeVisible();
    await expect(page.getByText(/Start with Apply below\./i)).toBeVisible();
  });
});
