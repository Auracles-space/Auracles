/**
 * Browser-level Developer platform workspace checks for Phase 5a Slice 14.
 *
 * The test mocks generated-client API calls at the network boundary. Backend
 * application approval, Partner purchase attribution, commission clearing,
 * webhook delivery, and payout rules are covered by FastAPI integration tests.
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

/**
 * Create a signed Developer session hint accepted by middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["developer"],
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
 * Install mocked Developer platform API routes.
 *
 * @param page - Active Playwright page.
 */
async function mockDeveloperPlatformApi(page: Page): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/auth/me") {
      await fulfillJson(route, {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Developer User",
        email: "developer@example.com",
        email_verified: true,
        id: "00000000-0000-4000-8000-000000000001",
        kyc_status: "verified",
        roles: ["developer"],
      });
      return;
    }

    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(["developer"]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/developer/applications/mine") {
      await fulfillJson(route, {
        applications: [
          {
            admin_feedback: null,
            company_name: "Partner Systems Inc.",
            created_at: "2026-06-11T10:00:00Z",
            id: "app_1",
            reviewed_at: "2026-06-11T11:00:00Z",
            reviewed_by: "admin_1",
            status: "approved",
            use_case: "Embed Auracles Framework discovery in a CRM.",
            user_id: "user_1",
            website: "https://partners.example.com",
          },
        ],
      });
      return;
    }

    if (path === "/v1/developer/api-keys" && request.method() === "GET") {
      await fulfillJson(route, {
        api_keys: [
          {
            created_at: "2026-06-11T10:00:00Z",
            expires_at: null,
            id: "key_1",
            key_prefix: "ak_live_123",
            last_used_at: "2026-06-11T12:00:00Z",
            name: "Production CRM",
            revoked_at: null,
            scopes: ["catalog:read", "purchase:write"],
            status: "active",
          },
        ],
      });
      return;
    }

    if (path === "/v1/developer/api-keys" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, string>;
      await fulfillJson(
        route,
        {
          created_at: "2026-06-11T12:00:00Z",
          expires_at: null,
          id: "key_2",
          key_prefix: "ak_new_456",
          last_used_at: null,
          name: body.name,
          raw_key: "ak_live_raw_once_for_e2e",
          revoked_at: null,
          scopes: ["catalog:read", "preview:read", "purchase:write"],
          status: "active",
        },
        201,
      );
      return;
    }

    if (path === "/v1/developer/tier") {
      await fulfillJson(route, {
        current_rate: "0.0800",
        current_tier: 2,
        next_tier: 3,
        next_tier_sales_required: 410,
        prior_30d_sales_count: 90,
        tier_recalculated_at: null,
        tiers: [],
      });
      return;
    }

    if (path === "/v1/developer/analytics/usage") {
      await fulfillJson(route, {
        average_response_ms: 133,
        by_endpoint: [
          {
            average_response_ms: 80,
            client_error_count: 1,
            endpoint: "/v1/partner/catalog",
            method: "GET",
            request_count: 2,
            server_error_count: 0,
            success_count: 1,
          },
        ],
        client_error_count: 1,
        server_error_count: 1,
        success_count: 8,
        total_requests: 10,
        window_days: 30,
      });
      return;
    }

    if (path === "/v1/developer/analytics/sales") {
      await fulfillJson(route, {
        by_framework: [
          {
            commission_amount: "17.50",
            framework_id: "framework_1",
            framework_title: "Governance Operating Model",
            gross_sale_amount: "350.00",
            sale_count: 3,
          },
        ],
        cleared_commission_amount: "10.00",
        gross_sale_amount: "350.00",
        paid_commission_amount: "0.00",
        pending_commission_amount: "5.00",
        status_counts: { cleared: 1, paid: 0, pending: 1, voided: 1 },
        total_commission_amount: "17.50",
        total_sales: 3,
        voided_commission_amount: "2.50",
        window_days: 30,
      });
      return;
    }

    if (path === "/v1/developer/webhooks" && request.method() === "GET") {
      await fulfillJson(route, {
        webhooks: [
          {
            active: true,
            created_at: "2026-06-11T10:00:00Z",
            events: ["purchase.confirmed"],
            id: "webhook_1",
            url: "https://partners.example.com/webhooks/auracles",
          },
        ],
      });
      return;
    }

    if (path === "/v1/developer/webhooks" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as {
        events: string[];
        url: string;
      };
      await fulfillJson(
        route,
        {
          active: true,
          created_at: "2026-06-11T12:00:00Z",
          events: body.events,
          id: "webhook_2",
          secret: "whsec_raw_once_for_e2e",
          url: body.url,
        },
        201,
      );
      return;
    }

    if (path === "/v1/developer/payouts" && request.method() === "GET") {
      await fulfillJson(route, {
        payouts: [
          {
            amount: "75.00",
            completed_at: null,
            currency: "USD",
            id: "payout_1",
            initiated_at: "2026-06-11T10:00:00Z",
            payout_account_id: payoutAccountId,
            provider_ref: null,
            status: "pending",
          },
        ],
      });
      return;
    }

    if (path === "/v1/developer/payouts" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, string>;
      await fulfillJson(route, {
        amount: body.amount,
        completed_at: null,
        currency: body.currency,
        id: "payout_2",
        initiated_at: "2026-06-11T12:00:00Z",
        payout_account_id: body.payout_account_id,
        provider_ref: null,
        status: "pending",
      });
      return;
    }

    if (path === "/v1/financials/payout-accounts") {
      await fulfillJson(route, {
        payout_accounts: [
          {
            account_type: "express",
            created_at: "2026-06-11T10:00:00Z",
            id: payoutAccountId,
            is_default: true,
            provider: "stripe",
            provider_account_ref: "acct_1234",
            verified_at: "2026-06-11T10:00:00Z",
          },
        ],
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked developer route." }, 404);
  });
}

test("Developer manages Partner API access, webhooks, analytics, and payout", async ({
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
  await mockDeveloperPlatformApi(page);

  await page.goto("/dashboard/developer");

  await expect(page.getByRole("heading", { name: "Developer platform" })).toBeVisible();
  await expect(page.getByText("$17.50").first()).toBeVisible();
  await expect(page.getByText("Governance Operating Model")).toBeVisible();

  await page.getByRole("button", { name: "API & Webhooks" }).click();
  await expect(page.getByText("Production CRM")).toBeVisible();
  await expect(page.getByText("GET /catalog", { exact: false }).first()).toBeVisible();
  await expect(
    page.getByText("https://partners.example.com/webhooks/auracles"),
  ).toBeVisible();

  await page.getByLabel("Key name").fill("Sandbox embed");
  await page.getByRole("button", { name: "Create key" }).click();
  await expect(page.getByText("ak_live_raw_once_for_e2e", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "I've saved it" }).click();

  await page.getByLabel("Endpoint URL").fill("https://partners.example.com/new-hook");
  await page.getByRole("button", { name: "Register webhook" }).click();
  await expect(page.getByText("whsec_raw_once_for_e2e", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Payouts & Tier" }).click();
  await expect(page.getByText("payout_1")).toBeVisible();
  await page.getByLabel("Amount").fill("10.00");
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Request payout" }).click();
  await expect(page.getByText("payout_2")).toBeVisible();
});


