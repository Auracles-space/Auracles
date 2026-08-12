/**
 * Browser-level reputation badge coverage for Phase 5e.
 *
 * The public Explore catalog is server-rendered (its API fetch happens on the
 * Next server and cannot be intercepted at the browser boundary), so the badge
 * is exercised here through the client-rendered Project workspace, where a
 * Contributor sees the Operator's reputation. Card/detail/profile rendering is
 * covered by the ReputationBadge unit tests. Backend gating + scoring stay
 * covered by FastAPI integration tests.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const projectId = "00000000-0000-4000-8000-000000000501";
const operatorId = "00000000-0000-4000-8000-000000000511";

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create a signed Contributor session hint accepted by auth middleware.
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

type OperatorReputation = {
  score: string | null;
  is_provisional: boolean;
  factors: { factor: string; label: string }[];
};

/**
 * Return the mocked Project read model the Contributor workspace loads.
 */
function project(operatorReputation: OperatorReputation) {
  return {
    accepted_proposal_id: null,
    budget_max: "5000.00",
    budget_min: "1000.00",
    category: "operations",
    closed_at: null,
    created_at: "2026-06-10T00:00:00Z",
    currency: "USD",
    deadline: "2026-08-01",
    delivered_at: null,
    description: "Evaluate the operator before bidding.",
    expires_at: "2026-07-10T00:00:00Z",
    id: projectId,
    milestone_plan_status: "draft",
    operator_id: operatorId,
    operator_reputation: operatorReputation,
    required_deliverables: [
      { description: "Operating model.", name: "Playbook" },
    ],
    status: "open",
    title: "Operator Reputation Project",
    updated_at: "2026-06-10T00:00:00Z",
  };
}

/**
 * Install mocked workspace routes serving one Project with operator reputation.
 */
async function mockWorkspaceApi(
  page: Page,
  operatorReputation: OperatorReputation,
): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }
    if (path === `/v1/projects/${projectId}`) {
      await fulfillJson(route, project(operatorReputation));
      return;
    }
    if (path.endsWith("/proposals") || path.endsWith("/proposals/mine")) {
      await fulfillJson(route, { proposals: [] });
      return;
    }
    if (path.endsWith("/milestones")) {
      await fulfillJson(route, { milestones: [] });
      return;
    }
    if (path.endsWith("/messages")) {
      await fulfillJson(route, { messages: [] });
      return;
    }
    await fulfillJson(route, {});
  });
  await mockSessionBootstrap(page, { displayName: "Contributor User", email: "contributor@example.com", roles: ["contributor"] });
}

test("workspace shows the Operator's numeric reputation to a Contributor", async ({
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
  await mockWorkspaceApi(page, {
    score: "66.00",
    is_provisional: false,
    factors: [{ factor: "purchase_activity", label: "strong" }],
  });

  await page.goto(`/projects/${projectId}`);

  await expect(
    page.getByRole("heading", { name: "Operator Reputation Project" }),
  ).toBeVisible();
  const badge = page.getByLabel("Reputation 66 out of 100");
  await expect(badge).toBeVisible();
  await expect(badge).toContainText("66");
});

test("workspace shows a New badge for a provisional Operator", async ({
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
  await mockWorkspaceApi(page, {
    score: null,
    is_provisional: true,
    factors: [],
  });

  await page.goto(`/projects/${projectId}`);

  await expect(
    page.getByRole("heading", { name: "Operator Reputation Project" }),
  ).toBeVisible();
  await expect(page.getByText("New", { exact: true })).toBeVisible();
});
