/**
 * Browser-level auth flow checks for Slice 10.
 *
 * These tests mock the generated-client backend boundary and verify that the
 * auth pages submit the expected flows, handle 2FA, and redirect based on JWT
 * roles. Backend integration remains covered by FastAPI tests.
 */
import { expect, type Page, test } from "@playwright/test";

type MockAuthMode = "2fa" | "operator-login";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";

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
      await fulfillJson(route, { message: "If email is new, verification sent." });
      return;
    }

    if (path === "/v1/auth/verify-email") {
      await fulfillJson(route, { message: "Email verified." });
      return;
    }

    if (path === "/v1/auth/me") {
      await fulfillJson(route, {
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

    if (path === "/v1/auth/forgot-password") {
      await fulfillJson(route, { message: "If email is valid, reset link sent." });
      return;
    }

    if (path === "/v1/auth/reset-password") {
      await fulfillJson(route, { message: "Password reset." });
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
      await fulfillJson(route, {
        access_token: fakeAccessToken(["operator"]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/auth/2fa/verify-login") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(["contributor"]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked auth route." }, 404);
  });
}

test("registers, verifies email, logs in, and lands by role", async ({ page }) => {
  await mockAuthApi(page, "operator-login");

  await page.goto("/register");
  await page.getByLabel("Display name").fill("Ada Markets");
  await page.getByLabel("Email").fill("ada@example.com");
  await page.getByLabel("Password").fill("StrongerPass123!");
  await page.getByLabel("Operator").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText(/verification sent/i)).toBeVisible();

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
