/**
 * Browser-level saved-search workflow coverage for Phase 5b-2 Slice 5.
 *
 * Backend alert dispatch is covered by FastAPI E2E tests. This browser spec
 * verifies that Explore and Settings pages call the saved-search API with the
 * expected filter snapshot and management actions.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const savedSearchId = "00000000-0000-4000-8000-000000000501";

/**
 * Convert text into base64url encoding.
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
 * Create a signed Operator session hint accepted by middleware.
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

type SavedSearchRequest = {
  alert_enabled?: boolean;
  filters?: Record<string, unknown>;
  name?: string;
};

type MockSavedSearch = {
  alert_enabled: boolean;
  created_at: string;
  filter_version: number;
  filters: Record<string, unknown>;
  id: string;
  last_alerted_at: string | null;
  last_alerted_framework_id: string | null;
  name: string;
  updated_at: string;
  user_id: string;
};

/**
 * Install saved-search API mocks and collect write payloads.
 *
 * @param page - Active Playwright page.
 */
async function mockSavedSearchApi(page: Page): Promise<{
  deletes: string[];
  patches: SavedSearchRequest[];
  posts: SavedSearchRequest[];
}> {
  const writes = {
    deletes: [] as string[],
    patches: [] as SavedSearchRequest[],
    posts: [] as SavedSearchRequest[],
  };
  let savedSearch: MockSavedSearch = {
    alert_enabled: false,
    created_at: "2026-06-11T09:00:00Z",
    filter_version: 1,
    filters: {
      category: "playbook",
      q: "risk",
      sort: "newest",
    },
    id: savedSearchId,
    last_alerted_at: null,
    last_alerted_framework_id: null,
    name: "Risk playbooks",
    updated_at: "2026-06-11T09:00:00Z",
    user_id: "00000000-0000-4000-8000-000000000001",
  };

  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/saved-searches" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as SavedSearchRequest;
      writes.posts.push(body);
      savedSearch = {
        ...savedSearch,
        alert_enabled: body.alert_enabled ?? false,
        filters: body.filters ?? {},
        name: body.name ?? savedSearch.name,
      };
      await fulfillJson(route, savedSearch, 201);
      return;
    }

    if (path === "/v1/saved-searches" && request.method() === "GET") {
      await fulfillJson(route, { saved_searches: [savedSearch] });
      return;
    }

    if (
      path === `/v1/saved-searches/${savedSearchId}` &&
      request.method() === "PATCH"
    ) {
      const body = JSON.parse(request.postData() ?? "{}") as SavedSearchRequest;
      writes.patches.push(body);
      savedSearch = { ...savedSearch, ...body };
      await fulfillJson(route, savedSearch);
      return;
    }

    if (
      path === `/v1/saved-searches/${savedSearchId}` &&
      request.method() === "DELETE"
    ) {
      writes.deletes.push(savedSearchId);
      await route.fulfill({
        body: "",
        headers: {
          "access-control-allow-credentials": "true",
          "access-control-allow-origin": appOrigin,
        },
        status: 204,
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled saved-search route." }, 404);
  });

  return writes;
}

test("Operator saves Explore filters and manages the saved search", async ({
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
  const writes = await mockSavedSearchApi(page);

  await page.goto("/explore?q=risk&category=playbook&page=3&sort=newest");
  await page.getByLabel("Saved search name").fill("Risk playbooks");
  await page.getByRole("button", { name: "Save search" }).click();
  await expect(page.getByText("Saved as Risk playbooks.")).toBeVisible();
  expect(writes.posts).toEqual([
    {
      alert_enabled: false,
      filters: {
        category: "playbook",
        q: "risk",
        sort: "newest",
      },
      name: "Risk playbooks",
    },
  ]);

  await page.goto("/settings/saved-searches");
  const row = page.getByRole("article", { name: "Risk playbooks" });
  await expect(row.getByText("Category: Playbook")).toBeVisible();
  await expect(row.getByRole("link", { name: "Open" })).toHaveAttribute(
    "href",
    "/explore?q=risk&category=playbook&sort=newest",
  );

  await row.getByRole("button", { name: "Enable alerts" }).click();
  await expect.poll(() => writes.patches).toContainEqual({ alert_enabled: true });

  await row.getByLabel("Saved search name").fill("Risk controls");
  await row.getByRole("button", { name: "Save name" }).click();
  await expect.poll(() => writes.patches).toContainEqual({ name: "Risk controls" });

  await page
    .getByRole("article", { name: "Risk controls" })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect.poll(() => writes.deletes).toEqual([savedSearchId]);
});
