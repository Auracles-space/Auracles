/**
 * Browser-level Operator purchase workspace checks for Slice 13.
 *
 * The test mocks client-side API calls at the network boundary. Backend
 * purchase, refund, invoice, and license rules remain covered by FastAPI
 * integration tests.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

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
 * Create a signed session hint value accepted by middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["operator"],
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
 * Install mocked Operator financial/library API routes.
 */
async function mockOperatorPurchaseApi(page: Page): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/library") {
      await fulfillJson(route, {
        items: [
          {
            currency: "USD",
            current_version: "1.0.1",
            expires_at: null,
            framework_id: "00000000-0000-4000-8000-000000000013",
            granted_at: "2026-06-09T00:00:00Z",
            license_id: "00000000-0000-4000-8000-000000000014",
            license_type: "team",
            price: "250.00",
            seats_total: 10,
            seats_used: 1,
            status: "active",
            thumbnail_key: null,
            title: "Diligence Control Playbook",
            version_at_grant: "1.0.0",
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      });
      return;
    }

    if (path === "/v1/explore/frameworks/00000000-0000-4000-8000-000000000013") {
      await fulfillJson(route, {
        artifacts: [
          {
            created_at: "2026-06-09T00:00:00Z",
            file_size: 2048,
            id: "00000000-0000-4000-8000-000000000015",
            mime_type: "application/pdf",
            name: "Implementation playbook.pdf",
          },
        ],
        category: "playbook",
        complexity: 3,
        currency: "USD",
        description: "Operator-ready controls for diligence workstreams.",
        function: "governance",
        id: "00000000-0000-4000-8000-000000000013",
        industry: "fund_management",
        jurisdiction: "US",
        lifecycle_stage: "growth",
        license_types: ["team"],
        org_size: "mid_market",
        owned: false,
        preview_artifact_id: null,
        preview_url: null,
        price: "250.00",
        published_at: "2026-06-09T00:00:00Z",
        rarity_score: "0.82",
        sector: "private_equity",
        tags: ["diligence", "controls"],
        thumbnail_key: null,
        title: "Diligence Control Playbook",
        version: "1.0.1",
      });
      return;
    }

    if (path === "/v1/financials/purchases" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            amount: "250.00",
            currency: "USD",
            framework_id: "00000000-0000-4000-8000-000000000013",
            framework_title: "Diligence Control Playbook",
            license_id: "00000000-0000-4000-8000-000000000014",
            license_type: "team",
            provider: "stripe",
            purchased_at: "2026-06-09T00:00:00Z",
            status: "completed",
            transaction_id: "00000000-0000-4000-8000-000000000099",
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      });
      return;
    }

    if (path.endsWith("/refund")) {
      await fulfillJson(route, {
        provider: "stripe",
        refund_id: "re_test_123",
        status: "refunded",
        transaction_id: "00000000-0000-4000-8000-000000000099",
      });
      return;
    }

    if (path.endsWith("/invoice")) {
      await fulfillJson(
        route,
        {
          status: "generating",
          transaction_id: "00000000-0000-4000-8000-000000000099",
        },
        202,
      );
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked purchase route." }, 404);
  });
}

test("Operator reviews licensed purchase, requests refund, and queues invoice", async ({
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
  await mockOperatorPurchaseApi(page);
  await mockSessionBootstrap(page);

  await page.goto("/library");

  await expect(page.getByText("Diligence Control Playbook").first()).toBeVisible();
  await expect(page.getByText("Implementation playbook.pdf")).toBeVisible();

  await page.getByRole("button", { name: "Refund" }).click();
  await expect(page.getByText("Refunded")).toBeVisible();

  await page.getByRole("button", { name: "Invoice" }).click();
  await expect(page.getByText("Invoice is being prepared.")).toBeVisible();
});
