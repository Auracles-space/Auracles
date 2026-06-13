/**
 * Browser-level admin workspace checks for Phase 5d Slice 7.
 *
 * The suite follows the repository pattern: backend authorization and state
 * rules are covered by FastAPI tests, while Playwright verifies the frontend
 * contract against mocked admin API responses.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

type AdminUserFixture = {
  created_at: string;
  display_name: string;
  email: string;
  roles: string[];
  suspended: boolean;
  suspended_at: string | null;
  user_id: string;
};

/**
 * Encode text as URL-safe base64 without padding.
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
 * Create a signed admin session hint accepted by middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["admin"],
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
 * Install mocked admin API routes with mutable user-directory state.
 *
 * @param page - Active Playwright page.
 */
async function mockAdminApi(page: Page): Promise<void> {
  let users: AdminUserFixture[] = [
    {
      created_at: "2026-06-10T09:00:00Z",
      display_name: "Ada Contributor",
      email: "ada@example.com",
      roles: ["contributor", "developer"],
      suspended: false,
      suspended_at: null,
      user_id: "user-1",
    },
  ];

  await page.route(`${apiOrigin}/v1/admin/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/admin/analytics/dashboard" && request.method() === "GET") {
      await fulfillJson(route, {
        active_users: {
          last_24_hours: 12,
          last_7_days: 44,
          last_30_days: 81,
        },
        attestations_issued: {
          last_24_hours: 1,
          last_7_days: 4,
          last_30_days: 9,
        },
        disputes_open: {
          attestations: 1,
          projects: 2,
          total: 3,
        },
        frameworks_published: {
          last_24_hours: 2,
          last_7_days: 8,
          last_30_days: 14,
          total: 25,
        },
        gmv: {
          last_30_days_by_source: {
            attestation_fee: "75.00",
            collection_purchase: "300.00",
            framework_purchase: "1200.00",
            project_milestone: "500.00",
          },
          last_30_days_total: "2075.00",
          last_7_days_by_source: {
            attestation_fee: "25.00",
            collection_purchase: "100.00",
            framework_purchase: "450.00",
            project_milestone: "200.00",
          },
          last_7_days_total: "775.00",
          today_by_source: {
            attestation_fee: "0.00",
            collection_purchase: "100.00",
            framework_purchase: "250.00",
            project_milestone: "0.00",
          },
          today_total: "350.00",
        },
        new_registrations: {
          last_24_hours: 3,
          last_7_days: 11,
          last_30_days: 29,
        },
        trend: [
          {
            active_users: 9,
            attestations_issued: 1,
            disputes_open: 2,
            frameworks_published: 1,
            gmv_total: "150.00",
            new_registrations: 2,
            snapshot_date: "2026-06-10",
          },
        ],
      });
      return;
    }

    if (path === "/v1/admin/moderation/queue" && request.method() === "GET") {
      const type = url.searchParams.get("type") ?? "all";
      const items = [
        {
          action_links: [
            {
              actor_role: "admin",
              method: "POST",
              path: "/v1/admin/frameworks/framework-1/suspend",
              rel: "suspend_framework",
            },
          ],
          artifact_id: "artifact-1",
          artifact_name: "blocked-playbook.pdf",
          contributor_id: "contributor-1",
          contributor_name: "Ada Contributor",
          details: {
            internal_jaccard: "0.9500",
          },
          framework_id: "framework-1",
          framework_title: "Blocked Similarity Framework",
          queue_type: "near_duplicate_block",
          signal_at: "2026-06-12T12:00:00Z",
          signal_id: "signal-1",
        },
        {
          action_links: [
            {
              actor_role: "contributor",
              method: "POST",
              path: "/v1/frameworks/framework-2/artifacts/artifact-2/accept-redaction",
              rel: "accept_redaction",
            },
          ],
          artifact_id: "artifact-2",
          artifact_name: "pii-playbook.pdf",
          contributor_id: "contributor-2",
          contributor_name: "Bayo Contributor",
          details: {
            pii_types_found: ["email"],
            redaction_available: true,
          },
          framework_id: "framework-2",
          framework_title: "PII Framework",
          queue_type: "pii_review",
          signal_at: "2026-06-12T13:00:00Z",
          signal_id: "signal-2",
        },
      ].filter((item) => type === "all" || item.queue_type === type);

      await fulfillJson(route, {
        items,
        page: 1,
        page_size: 20,
        total: items.length,
      });
      return;
    }

    if (path === "/v1/admin/users" && request.method() === "GET") {
      await fulfillJson(route, {
        items: users,
        page: 1,
        page_size: 20,
        total: users.length,
      });
      return;
    }

    if (path === "/v1/admin/users/user-1/suspend" && request.method() === "POST") {
      users = users.map((user) =>
        user.user_id === "user-1"
          ? {
              ...user,
              suspended: true,
              suspended_at: "2026-06-12T15:00:00Z",
            }
          : user,
      );
      await fulfillJson(route, {
        suspended: true,
        suspended_at: "2026-06-12T15:00:00Z",
        suspended_by: "00000000-0000-4000-8000-000000000001",
        suspension_reason: "Fraud review",
        user_id: "user-1",
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked admin route." }, 404);
  });
}

test("admin can use analytics, moderation, and user controls", async ({
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
  await mockAdminApi(page);

  await page.goto("/admin/analytics");
  await expect(page.getByRole("heading", { name: "Platform analytics" })).toBeVisible();
  await expect(page.getByText("$2,075")).toBeVisible();

  await page.getByRole("link", { name: "Moderation" }).click();
  await expect(page.getByRole("heading", { name: "Moderation queue" })).toBeVisible();
  await page.getByLabel("Queue type").selectOption("pii_review");
  await expect(page.getByText("PII Framework")).toBeVisible();
  await expect(page.getByText("Contributor follow-up required")).toBeVisible();

  await page.getByRole("link", { name: "Users" }).click();
  await expect(page.getByRole("heading", { name: "User controls" })).toBeVisible();
  await expect(page.getByText("ada@example.com")).toBeVisible();
  await page.getByRole("button", { name: "Suspend" }).click();
  await page.getByLabel("Reason").fill("Fraud review");
  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Confirm suspension" }).click();
  await expect(
    page.getByRole("article", { name: "Ada Contributor" }).getByText("Suspended", {
      exact: true,
    }),
  ).toBeVisible();
});
