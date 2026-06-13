/**
 * Browser-level notification preferences settings coverage.
 *
 * Follows the repository pattern of mocking API responses at the browser
 * boundary while backend tests cover the real notification delivery gates.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

/**
 * Encode JSON as URL-safe base64 without padding.
 *
 * @param value - Raw JSON payload.
 * @returns URL-safe base64 string.
 */
function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create a signed operator session hint accepted by middleware.
 *
 * @returns Signed session-hint cookie value.
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
 * Fulfill mocked API responses with browser-safe CORS headers.
 *
 * @param route - Active Playwright route.
 * @param body - JSON payload to return.
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

test("Operator updates notification preferences from the dedicated settings page", async ({
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

  let matrix = {
    categories: [
      {
        category: "discovery",
        label: "Discovery",
        preferences: [
          {
            channels: [
              { channel: "email", enabled: true, locked: false },
              { channel: "in_app", enabled: true, locked: false },
            ],
            description: "Receive saved search alert updates.",
            label: "Saved Search Alert",
            notification_type: "saved_search_alert",
          },
        ],
      },
      {
        category: "financial",
        label: "Financial",
        preferences: [
          {
            channels: [
              { channel: "email", enabled: true, locked: true },
              { channel: "in_app", enabled: true, locked: true },
            ],
            description: "Receive dispute resolved release updates.",
            label: "Dispute Resolved Release",
            notification_type: "dispute_resolved_release",
          },
        ],
      },
    ],
  };
  const patchBodies: Array<unknown> = [];

  await page.route(`${apiOrigin}/v1/settings/notification-preferences`, async (route) => {
    const request = route.request();

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (request.method() === "GET") {
      await fulfillJson(route, matrix);
      return;
    }

    if (request.method() === "PATCH") {
      const body = JSON.parse(request.postData() ?? "{}");
      patchBodies.push(body);
      matrix = {
        categories: [
          {
            category: "discovery",
            label: "Discovery",
            preferences: [
              {
                channels: [
                  { channel: "email", enabled: false, locked: false },
                  { channel: "in_app", enabled: true, locked: false },
                ],
                description: "Receive saved search alert updates.",
                label: "Saved Search Alert",
                notification_type: "saved_search_alert",
              },
            ],
          },
          matrix.categories[1],
        ],
      };
      await fulfillJson(route, matrix);
      return;
    }

    await fulfillJson(route, { detail: "Unhandled notification preferences route." }, 404);
  });

  await page.goto("/settings/notifications");

  await expect(
    page.getByRole("heading", { name: "Notifications" }),
  ).toBeVisible();

  const savedSearchEmailToggle = page.getByRole("checkbox", {
    name: /saved search alert email/i,
  });
  await expect(savedSearchEmailToggle).toBeChecked();
  await savedSearchEmailToggle.click();

  await expect.poll(() => patchBodies).toEqual([
    {
      updates: [
        {
          channel: "email",
          enabled: false,
          notification_type: "saved_search_alert",
        },
      ],
    },
  ]);
  await expect(savedSearchEmailToggle).not.toBeChecked();
  await expect(page.getByText("Preferences updated.")).toBeVisible();

  const criticalEmailToggle = page.getByRole("checkbox", {
    name: /dispute resolved release email/i,
  });
  await expect(criticalEmailToggle).toBeDisabled();
  await expect(page.getByText("Always on")).toBeVisible();
});
