/**
 * Browser-level Contributor financial workspace checks for Slice 14.
 *
 * The test mocks generated-client API calls at the network boundary. Backend
 * earnings, KYC, 2FA, and payout state-machine rules remain covered by FastAPI
 * service and integration tests.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const payoutAccountId = "00000000-0000-4000-8000-000000000020";

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create a signed contributor session hint accepted by middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["contributor"],
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

function fakeAccessToken(roles: string[]): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      exp: Math.floor(Date.now() / 1000) + 900,
      roles,
      sub: "00000000-0000-4000-8000-000000000001",
      totp_verified: true,
    }),
  );
  return `${header}.${payload}.signature`;
}

async function mockAuthenticatedShellApi(page: Page): Promise<void> {
  await page.route(`${apiOrigin}/v1/auth/me`, async (route) => {
    await fulfillJson(route, {
      avatar_url: null,
      deactivated_at: null,
      display_name: "Contributor User",
      email: "contributor@example.com",
      email_verified: true,
      id: "00000000-0000-4000-8000-000000000001",
      kyc_status: "verified",
      roles: ["contributor"],
    });
  });

  await page.route(`${apiOrigin}/v1/auth/refresh`, async (route) => {
    await fulfillJson(route, {
      access_token: fakeAccessToken(["contributor"]),
      expires_in: 900,
      token_type: "bearer",
    });
  });
}

/**
 * Fulfill mocked API responses with browser-accepted CORS headers.
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
 * Install mocked Contributor financial API routes.
 *
 * @param page - Active Playwright page.
 */
async function mockContributorFinancialsApi(page: Page): Promise<void> {
  await page.route(`${apiOrigin}/v1/financials/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/financials/earnings") {
      await fulfillJson(route, {
        available_balance: "637.50",
        commission_rate: "0.15",
        currency: "USD",
        gross_revenue: "1000.00",
        minimum_payout: "50.00",
        pending_clearance: "250.00",
      });
      return;
    }

    if (path === "/v1/financials/payout-accounts" && request.method() === "GET") {
      await fulfillJson(route, {
        payout_accounts: [
          {
            account_type: "express",
            created_at: "2026-06-09T00:00:00Z",
            id: payoutAccountId,
            is_default: true,
            provider: "stripe",
            provider_account_ref: "****acct",
            verified_at: "2026-06-09T00:00:00Z",
          },
        ],
      });
      return;
    }

    if (path === "/v1/financials/payout-accounts/onboard") {
      await fulfillJson(route, {
        onboarding_url: "https://connect.stripe.test/onboard",
        payout_account: {
          account_type: "express",
          created_at: "2026-06-09T00:00:00Z",
          id: payoutAccountId,
          is_default: true,
          provider: "stripe",
          provider_account_ref: "****acct",
          verified_at: "2026-06-09T00:00:00Z",
        },
        provider: "stripe",
      });
      return;
    }

    if (path === "/v1/financials/payouts" && request.method() === "GET") {
      await fulfillJson(route, {
        payouts: [
          {
            amount: "100.00",
            commission_deducted: "15.00",
            completed_at: null,
            currency: "USD",
            id: "00000000-0000-4000-8000-000000000030",
            initiated_at: "2026-06-09T00:00:00Z",
            net_amount: "85.00",
            payout_account_id: payoutAccountId,
            provider_ref: "****tr_1",
            status: "pending",
          },
        ],
      });
      return;
    }

    if (path === "/v1/financials/payouts" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, string>;
      await fulfillJson(
        route,
        {
          amount: body.amount,
          commission_deducted: "30.00",
          completed_at: null,
          currency: body.currency,
          id: "00000000-0000-4000-8000-000000000031",
          initiated_at: "2026-06-09T01:00:00Z",
          net_amount: "170.00",
          payout_account_id: body.payout_account_id,
          provider_ref: null,
          status: "pending",
        },
        201,
      );
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked financial route." }, 404);
  });
}

test("Contributor views earnings, payout account, and requests payout", async ({
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
  await mockAuthenticatedShellApi(page);
  await mockContributorFinancialsApi(page);

  await page.goto("/dashboard/earnings");
  await expect(page).toHaveURL(/\/dashboard\/financials/);
  await expect(page.getByRole("heading", { name: "Financials" })).toBeVisible();
  await expect(page.getByText("$637.50")).toBeVisible();
  await expect(page.getByText("Minimum payout $50")).toBeVisible();

  await page.goto("/settings/payout-accounts");
  await expect(page.getByRole("heading", { name: "Payout accounts" })).toBeVisible();
  await expect(page.getByText("****acct")).toBeVisible();
  await expect(page.getByText("Verified")).toBeVisible();

  await page.goto("/dashboard/payouts");
  await expect(page).toHaveURL(/\/dashboard\/financials/);
  await expect(page.getByText("****tr_1")).toBeVisible();
  await page.getByRole("button", { name: "Request payout" }).click();
  await page.getByLabel("Amount").fill("200.00");
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Submit payout request" }).click();

  await expect(page.getByText("$170")).toBeVisible();
  await expect(page.getByText("Pending transfer")).toBeVisible();
});
