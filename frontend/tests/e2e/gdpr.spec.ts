/**
 * Browser-level GDPR settings checks for Phase 5c Slice 8.
 *
 * The suite follows the repository's frontend contract pattern: it mocks API
 * responses at the browser boundary while backend integration tests cover the
 * real deletion, export, and anonymisation state machines.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

/**
 * Encode session-hint JSON for middleware cookies.
 *
 * @param value - Plain JSON string payload.
 * @returns URL-safe base64 variant without padding.
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
 * Fulfill mocked API responses with browser-accepted CORS headers.
 *
 * @param route - Active Playwright route.
 * @param body - JSON payload to send.
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

type DeletionStatus = "none" | "blocked" | "scheduled";
type ExportStatus = "failed" | "pending" | "processing" | "ready" | "expired" | null;

/**
 * Install mocked GDPR API routes with mutable in-memory state.
 *
 * @param page - Active Playwright page.
 * @param options - Initial mocked state for one test.
 */
async function mockGdprApi(
  page: Page,
  options: {
    consentMissingDocuments?: string[];
    deletionStatus?: DeletionStatus;
    exportStatus?: ExportStatus;
  },
): Promise<void> {
  let consentMissingDocuments = options.consentMissingDocuments ?? [];
  let deletionStatus = options.deletionStatus ?? "none";
  let exportStatus = options.exportStatus ?? null;

  await page.route(`${apiOrigin}/v1/gdpr/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/gdpr/exports/latest" && request.method() === "GET") {
      if (exportStatus === null) {
        await fulfillJson(route, { detail: "No export request found." }, 404);
        return;
      }

      await fulfillJson(route, {
        completed_at: exportStatus === "ready" ? "2026-06-12T10:00:00Z" : null,
        created_at: "2026-06-12T09:00:00Z",
        expires_at: exportStatus === "ready" ? "2026-06-19T10:00:00Z" : null,
        failure_reason:
          exportStatus === "failed" ? "Export generation failed." : null,
        id: "00000000-0000-4000-8000-000000000050",
        status: exportStatus,
      });
      return;
    }

    if (path === "/v1/gdpr/exports" && request.method() === "POST") {
      exportStatus = "pending";
      await fulfillJson(
        route,
        {
          completed_at: null,
          created_at: "2026-06-12T09:00:00Z",
          expires_at: null,
          failure_reason: null,
          id: "00000000-0000-4000-8000-000000000050",
          status: "pending",
        },
        202,
      );
      return;
    }

    if (
      path === "/v1/gdpr/exports/00000000-0000-4000-8000-000000000050/download" &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, { status: "download_started" }, 200);
      return;
    }

    if (path === "/v1/gdpr/consent" && request.method() === "GET") {
      await fulfillJson(route, {
        current_versions: {
          privacy_policy: "2026-06-11",
          terms_of_service: "2026-06-11",
        },
        items: consentMissingDocuments.length
          ? []
          : [
              {
                accepted_at: "2026-06-11T08:00:00Z",
                document_type: "terms_of_service",
                id: "00000000-0000-4000-8000-000000000060",
                version: "2026-06-11",
              },
              {
                accepted_at: "2026-06-11T08:00:05Z",
                document_type: "privacy_policy",
                id: "00000000-0000-4000-8000-000000000061",
                version: "2026-06-11",
              },
            ],
        missing_documents: consentMissingDocuments,
      });
      return;
    }

    if (path === "/v1/gdpr/consent" && request.method() === "POST") {
      consentMissingDocuments = [];
      await fulfillJson(route, {
        current_versions: {
          privacy_policy: "2026-06-11",
          terms_of_service: "2026-06-11",
        },
        items: [
          {
            accepted_at: "2026-06-12T10:00:00Z",
            document_type: "terms_of_service",
            id: "00000000-0000-4000-8000-000000000060",
            version: "2026-06-11",
          },
          {
            accepted_at: "2026-06-12T10:00:00Z",
            document_type: "privacy_policy",
            id: "00000000-0000-4000-8000-000000000061",
            version: "2026-06-11",
          },
        ],
        missing_documents: [],
      });
      return;
    }

    if (path === "/v1/gdpr/account-deletion" && request.method() === "GET") {
      if (deletionStatus === "blocked") {
        await fulfillJson(route, {
          blocked_reasons: [
            {
              code: "active_projects",
              count: 1,
              message: "You still have 1 active project to close.",
            },
          ],
          scheduled_for: null,
          status: "blocked",
        });
        return;
      }

      if (deletionStatus === "scheduled") {
        await fulfillJson(route, {
          blocked_reasons: [],
          scheduled_for: "2026-06-26T09:00:00Z",
          status: "scheduled",
        });
        return;
      }

      await fulfillJson(route, {
        blocked_reasons: [],
        scheduled_for: null,
        status: "none",
      });
      return;
    }

    if (path === "/v1/gdpr/account-deletion" && request.method() === "POST") {
      if (deletionStatus === "blocked") {
        await fulfillJson(
          route,
          {
            blocked_reasons: [
              {
                code: "active_projects",
                count: 1,
                message: "You still have 1 active project to close.",
              },
            ],
            scheduled_for: null,
            status: "blocked",
          },
          409,
        );
        return;
      }

      deletionStatus = "scheduled";
      await fulfillJson(
        route,
        {
          blocked_reasons: [],
          scheduled_for: "2026-06-26T09:00:00Z",
          status: "scheduled",
        },
        202,
      );
      return;
    }

    if (
      path === "/v1/gdpr/account-deletion/cancel" &&
      request.method() === "POST"
    ) {
      deletionStatus = "none";
      await fulfillJson(route, {
        blocked_reasons: [],
        scheduled_for: null,
        status: "none",
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked GDPR route." }, 404);
  });
}

test.beforeEach(async ({ context }) => {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      name: "session_hint",
      path: "/",
      value: sessionHintValue(),
    },
  ]);
});

test("Operator requests an export and sees it move into preparing state", async ({
  page,
}) => {
  await mockGdprApi(page, { exportStatus: null });

  await page.goto("/settings/account");
  await expect(page.getByRole("heading", { name: "Identity and access" })).toBeVisible();
  await expect(page.getByText("No data export has been requested yet.")).toBeVisible();

  await page.getByRole("button", { name: "Request export" }).click();

  await expect(
    page.getByText("Export requested. We will prepare your JSON bundle shortly."),
  ).toBeVisible();
  await expect(page.getByText("Your latest export is being prepared.")).toBeVisible();
});

test("Operator can trigger the latest ready export download from account settings", async ({
  page,
}) => {
  await mockGdprApi(page, { exportStatus: "ready" });

  const downloadRequest = page.waitForRequest(
    `${apiOrigin}/v1/gdpr/exports/00000000-0000-4000-8000-000000000050/download`,
  );
  await page.goto("/settings/account");
  await expect(page.getByText("Ready for download.")).toBeVisible();

  await page.getByRole("button", { name: "Download latest export" }).click();

  await downloadRequest;
  await expect(page.getByText("Download started.")).toBeVisible();
  await expect(page).toHaveURL(`${appOrigin}/settings/account`);
});

test("Consent page lets a user accept missing legal versions", async ({ page }) => {
  await mockGdprApi(page, {
    consentMissingDocuments: ["terms_of_service", "privacy_policy"],
  });

  await page.goto("/settings/consent");
  await expect(
    page.getByRole("heading", { name: "Consent", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("New legal versions require your acceptance."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Accept current versions" }).click();

  await expect(page.getByRole("status")).toContainText(
    "You are up to date on legal consent.",
  );
});

test("Blocked delete-account flow surfaces obligations without scheduling", async ({
  page,
}) => {
  await mockGdprApi(page, { deletionStatus: "blocked" });

  await page.goto("/settings/account");
  await expect(
    page.getByText("Deletion is blocked until the obligations below are resolved."),
  ).toBeVisible();
  await expect(
    page.getByText("You still have 1 active project to close. (1)"),
  ).toBeVisible();

  await page.getByLabel("Current password").fill("CorrectHorse9");
  await page.getByRole("button", { name: "Delete account" }).click();

  await expect(
    page.getByText("Deletion is blocked until the obligations below are resolved."),
  ).toBeVisible();
  await expect(page.getByText("Your account is scheduled for deletion.")).toHaveCount(0);
});

test("User can schedule and then cancel account deletion", async ({ page }) => {
  await mockGdprApi(page, { deletionStatus: "none" });

  await page.goto("/settings/account");
  await page.getByLabel("Current password").fill("CorrectHorse9");
  await page.getByRole("button", { name: "Delete account" }).click();

  await expect(
    page.getByText("Your account is scheduled for deletion."),
  ).toBeVisible();
  await expect(
    page.getByText(/You can cancel this request until/i),
  ).toBeVisible();

  await page.getByRole("button", { name: "Cancel deletion request" }).click();

  await expect(
    page.getByText("Your account is scheduled for deletion."),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Delete account" }),
  ).toBeVisible();
});
