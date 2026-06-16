/**
 * Browser-level auth flow checks for Slice 10.
 *
 * These tests mock the generated-client backend boundary and verify that the
 * auth pages submit the expected flows, handle 2FA, and redirect based on JWT
 * roles. Backend integration remains covered by FastAPI tests.
 */
import { createHmac } from "node:crypto";

import { expect, type BrowserContext, type Page, test } from "@playwright/test";

type MockAuthMode = "2fa" | "operator-login";
type MockCurrentUser = {
  avatar_url?: string | null;
  display_name: string;
  email: string;
  email_verified: boolean;
  kyc_status: string;
  roles: string[];
};

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create an unsigned JWT-shaped token for frontend role-routing tests.
 *
 * @param roles - Roles to encode in the public JWT payload.
 */
function fakeAccessToken(roles: string[]): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      exp: Math.floor(Date.now() / 1000) + 900,
      roles,
      sub: "00000000-0000-4000-8000-000000000001",
      totp_verified: roles.includes("contributor"),
    }),
  );
  return `${header}.${payload}.signature`;
}

/**
 * Create a signed session hint cookie accepted by frontend middleware.
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
        user_id: "00000000-0000-4000-8000-000000000001",
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
 * Seed the browser with a verified session-hint cookie before navigation.
 *
 * @param context - Active Playwright browser context.
 * @param roles - Roles encoded into the middleware hint.
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
 * Install auth API mocks for the current browser page.
 *
 * @param page - Active Playwright page.
 * @param mode - Login behavior for this scenario.
 */
async function mockAuthApi(page: Page, mode: MockAuthMode): Promise<void> {
  await page.route(`${apiOrigin}/v1/auth/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/auth/register") {
      await fulfillJson(route, { message: "If that email needs verification, we've sent a verification link. Check your inbox." });
      return;
    }

    if (path === "/v1/auth/me") {
      await fulfillJson(route, {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Ada Markets",
        email: "ada@example.com",
        email_verified: true,
        id: "00000000-0000-4000-8000-000000000001",
        kyc_status: "unverified",
        roles: ["operator"],
      });
      return;
    }

    if (path === "/v1/auth/verify-email") {
      await fulfillJson(route, { message: "Email verified." });
      return;
    }

    if (path === "/v1/auth/forgot-password") {
      await fulfillJson(route, { message: "If email is valid, reset link sent." });
      return;
    }

    if (path === "/v1/auth/reset-password") {
      await fulfillJson(route, { message: "Password reset." });
      return;
    }

    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(["operator"]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/auth/login" && mode === "2fa") {
      await fulfillJson(route, {
        challenge_token: "challenge-token",
        expires_in: 900,
        requires_2fa: true,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/auth/login") {
      await fulfillJson(
        route,
        {
          access_token: fakeAccessToken(["operator"]),
          expires_in: 900,
          token_type: "bearer",
        },
        200,
        { "set-cookie": sessionHintCookie(["operator"]) },
      );
      return;
    }

    if (path === "/v1/auth/2fa/verify-login") {
      await fulfillJson(
        route,
        {
          access_token: fakeAccessToken(["contributor"]),
          expires_in: 900,
          token_type: "bearer",
        },
        200,
        { "set-cookie": sessionHintCookie(["contributor"]) },
      );
      return;
    }

    if (path === "/v1/auth/logout") {
      await fulfillJson(route, { message: "Logged out." });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked auth route." }, 404);
  });
}

/**
 * Mock refresh and current-user reads used by authenticated shell/profile UI.
 *
 * @param page - Active Playwright page.
 * @param currentUser - Authenticated user payload returned by `/v1/auth/me`.
 */
async function mockAuthenticatedShellApi(
  page: Page,
  currentUser: MockCurrentUser,
): Promise<void> {
  await page.route(`${apiOrigin}/v1/auth/me`, async (route) => {
    await fulfillJson(route, {
      avatar_url: currentUser.avatar_url ?? null,
      deactivated_at: null,
      display_name: currentUser.display_name,
      email: currentUser.email,
      email_verified: currentUser.email_verified,
      id: "00000000-0000-4000-8000-000000000001",
      kyc_status: currentUser.kyc_status,
      roles: currentUser.roles,
    });
  });

  await page.route(`${apiOrigin}/v1/auth/refresh`, async (route) => {
    await fulfillJson(route, {
      access_token: fakeAccessToken(currentUser.roles),
      expires_in: 900,
      token_type: "bearer",
    });
  });

  await page.route(`${apiOrigin}/v1/auth/logout`, async (route) => {
    await fulfillJson(route, { message: "Logged out." });
  });
}

test("registers, verifies email, logs in, and lands by role", async ({ page }) => {
  await mockAuthApi(page, "operator-login");

  await page.goto("/register");
  await page.getByLabel("Display name").fill("Ada Markets");
  await page.getByLabel("Email").fill("ada@example.com");
  await page.getByLabel("Password").fill("StrongerPass123!");
  await page.getByLabel("Operator").check();
  await page.getByLabel(/I agree to the Terms/).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText(/verification link/i)).toBeVisible();

  await page.goto("/verify-email?token=test-token");
  await page.getByRole("button", { name: "Verify email" }).click();
  await expect(page.getByText("Email verified.")).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.com");
  await page.getByLabel("Password").fill("StrongerPass123!");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/settings\/onboarding$/);
  await expect(page.getByText(/browse and preview frameworks/i)).toBeVisible();
});

test("completes login through a 2FA challenge", async ({ page }) => {
  await mockAuthApi(page, "2fa");

  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.com");
  await page.getByLabel("Password").fill("StrongerPass123!");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/2fa-challenge\?challenge=challenge-token$/);
  await page.waitForLoadState("networkidle");

  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify login" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("runs the password reset browser loop", async ({ page }) => {
  await mockAuthApi(page, "operator-login");

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("ada@example.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/reset link sent/i)).toBeVisible();

  await page.goto("/reset-password?token=reset-token");
  await page.getByLabel("New password").fill("NewStrongPass123!");
  await page.getByRole("button", { name: "Save password" }).click();
  await expect(page.getByText("Password reset.")).toBeVisible();
});

test("redirects logged-out visitors from protected routes to login", async ({ page }) => {
  await page.goto("/library");

  await expect(page).toHaveURL(/\/login\?next=%2Flibrary$/);
});

test("redirects wrong-role users away from admin and hides the Admin nav link", async ({
  context,
  page,
}) => {
  await mockAuthenticatedShellApi(page, {
    display_name: "Ada Markets",
    email: "ada@example.com",
    email_verified: true,
    kyc_status: "verified",
    roles: ["operator"],
  });
  await seedSessionHint(context, ["operator"]);

  await page.goto("/admin");

  await expect(page).toHaveURL(/\/explore$/);
  await expect(page.getByRole("link", { name: /^admin$/i })).toHaveCount(0);
});

test("allows admins into admin routes and shows the Admin nav link", async ({
  context,
  page,
}) => {
  await mockAuthenticatedShellApi(page, {
    display_name: "Root Admin",
    email: "admin@example.com",
    email_verified: true,
    kyc_status: "verified",
    roles: ["admin"],
  });
  await seedSessionHint(context, ["admin"]);

  await page.goto("/admin/analytics");

  await expect(page).toHaveURL(`${appOrigin}/admin/analytics`);
  await expect(page.getByRole("link", { name: /^admin$/i })).toBeVisible();
});

test("signs out and forces protected routes back through login", async ({
  context,
  page,
}) => {
  await mockAuthenticatedShellApi(page, {
    display_name: "Ada Markets",
    email: "ada@example.com",
    email_verified: false,
    kyc_status: "pending",
    roles: ["operator"],
  });
  await seedSessionHint(context, ["operator"]);

  await page.goto("/settings/profile");
  await page.getByText("Ada Markets").first().click();
  await page
    .locator("aside")
    .getByRole("button", { name: /sign out/i })
    .click({ force: true });
  await expect(page).toHaveURL(`${appOrigin}/login`);

  await page.goto("/library");
  await expect(page).toHaveURL(/\/login\?next=%2Flibrary$/);
});
