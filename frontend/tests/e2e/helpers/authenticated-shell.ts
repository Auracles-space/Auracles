/**
 * Shared session mocks for authenticated end-to-end flows.
 *
 * Every authenticated page bootstraps its session before rendering anything:
 * it refreshes the access token and reads the current user. A spec that mocks
 * only its own feature endpoints leaves those two unanswered, the client reads
 * the failure as a dead session, and the page redirects to /login before a
 * single assertion runs — which looks like a broken feature and is not one.
 *
 * Register this AFTER a spec's own catch-all route: Playwright matches
 * handlers in reverse registration order, so the last one registered wins.
 */
import type { Page } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000001";

type AuthenticatedShellOptions = {
  displayName?: string;
  email?: string;
  kycStatus?: string;
  roles?: string[];
  userId?: string;
};

/**
 * Encode a value as unpadded base64url.
 *
 * @param value - Raw string to encode.
 * @returns The base64url representation.
 */
function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Build an access token the client will parse but no server will accept.
 *
 * The client only reads the claims to drive UI state; the signature is never
 * verified in the browser, so an unsigned token is enough here and cannot be
 * mistaken for a credential anywhere real.
 *
 * @param roles - Roles to encode in the token claims.
 * @param userId - Subject claim.
 * @returns A JWT-shaped string.
 */
function fakeAccessToken(roles: string[], userId: string): string {
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
 * Fulfill a mocked response with the CORS headers the browser requires.
 *
 * @param route - Playwright route to fulfill.
 * @param body - JSON response payload.
 */
async function fulfillJson(
  route: Parameters<Parameters<Page["route"]>[1]>[0],
  body: unknown,
): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    headers: {
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type,authorization",
      "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
      "access-control-allow-origin": "http://127.0.0.1:3100",
      "content-type": "application/json",
    },
    status: 200,
  });
}

/**
 * Answer the session bootstrap calls every authenticated page makes.
 *
 * @param page - Page to install the routes on.
 * @param options - Identity to present; defaults to a verified Operator.
 */
export async function mockSessionBootstrap(
  page: Page,
  options: AuthenticatedShellOptions = {},
): Promise<void> {
  const {
    displayName = "Operator User",
    email = "operator@example.com",
    kycStatus = "verified",
    roles = ["operator"],
    userId = DEFAULT_USER_ID,
  } = options;

  await page.route(`${apiOrigin}/v1/auth/me`, async (route) => {
    await fulfillJson(route, {
      avatar_url: null,
      deactivated_at: null,
      display_name: displayName,
      email,
      email_verified: true,
      id: userId,
      kyc_status: kycStatus,
      roles,
    });
  });

  await page.route(`${apiOrigin}/v1/auth/refresh`, async (route) => {
    await fulfillJson(route, {
      access_token: fakeAccessToken(roles, userId),
      expires_in: 900,
      token_type: "bearer",
    });
  });
}
