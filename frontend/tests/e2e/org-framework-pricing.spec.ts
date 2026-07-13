/**
 * Browser-level per-org framework pricing checks.
 *
 * This suite stands up a tiny local stub backend so both Next.js server-side
 * data fetching and browser-side checkout calls see the same mocked contract.
 * It verifies that an org-tier framework shows the org price on detail, then
 * routes checkout through the org purchase path when an eligible org buyer is
 * selected on a 375px viewport.
 */
import { createHmac } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

import { expect, type BrowserContext, test } from "@playwright/test";

const backendOrigin = "http://127.0.0.1:8000";
const frameworkId = "framework-1";
const orgId = "org-1";
const sessionHintSecret = "auracles-e2e-secret";
const userId = "00000000-0000-4000-8000-000000000001";

let backendServer: Server | null = null;
let orgPurchaseCalls = 0;
let selfPurchaseCalls = 0;
let lastOrgPurchaseBody: Record<string, unknown> | null = null;

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create an unsigned JWT-shaped token for frontend routing tests.
 */
function fakeAccessToken(roles: string[]): string {
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
 * Create a signed session-hint cookie accepted by frontend middleware.
 */
function sessionHintCookie(roles: string[]): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles,
        totp_verified: true,
        user_id: userId,
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
 * Seed the browser with a verified authenticated session hint.
 */
async function seedSessionHint(
  context: BrowserContext,
  roles: string[],
): Promise<void> {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      name: "session_hint",
      path: "/",
      sameSite: "Lax",
      secure: false,
      value: sessionHintCookie(roles),
    },
  ]);
}

/**
 * Collect and parse a JSON request body.
 */
async function readJsonBody(
  request: IncomingMessage,
): Promise<Record<string, unknown> | null> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  if (chunks.length === 0) {
    return null;
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf-8")) as Record<string, unknown>;
}

/**
 * Send a JSON response with permissive local-dev CORS headers.
 */
function sendJson(
  response: ServerResponse,
  body: unknown,
  status = 200,
): void {
  response.statusCode = status;
  response.setHeader("access-control-allow-credentials", "true");
  response.setHeader("access-control-allow-headers", "content-type,authorization");
  response.setHeader("access-control-allow-methods", "GET,POST,PATCH,PUT,DELETE,OPTIONS");
  response.setHeader("access-control-allow-origin", "http://127.0.0.1:3100");
  response.setHeader("content-type", "application/json");
  response.end(JSON.stringify(body));
}

/**
 * Return the shared mocked framework detail payload.
 */
function frameworkDetail() {
  return {
    artifacts: [],
    attestation_badge: null,
    attestation_badges: [],
    average_review_score: null,
    category: "playbook",
    complexity: 3,
    contributor_id: "seller-1",
    contributor_name: "Mara Okafor",
    contributor_org_id: null,
    contributor_reputation_score: null,
    contributor_slug: "mara-okafor",
    contributor_verification_level: null,
    currency: "USD",
    description: "Operator-ready controls for diligence workstreams.",
    function: "governance",
    id: frameworkId,
    industry: "fund_management",
    jurisdiction: "US",
    lifecycle_stage: "growth",
    license_types: ["single_user", "organizational"],
    org_price: "900.00",
    org_size: "mid_market",
    owned: false,
    preview_artifact_id: null,
    preview_url: null,
    price: "250.00",
    published_at: "2026-06-09T00:00:00Z",
    rarity_score: "0.82",
    reputation: null,
    review_count: 0,
    sector: "private_equity",
    tags: ["diligence", "controls"],
    thumbnail_key: null,
    title: "Diligence Control Playbook",
    version: "1.0.0",
  };
}

/**
 * Start a minimal local backend that satisfies this spec's API contract.
 */
async function startBackendStub(): Promise<void> {
  orgPurchaseCalls = 0;
  selfPurchaseCalls = 0;
  lastOrgPurchaseBody = null;

  backendServer = createServer(async (request, response) => {
    const method = request.method ?? "GET";
    const url = new URL(request.url ?? "/", backendOrigin);
    const path = url.pathname;

    if (method === "OPTIONS") {
      sendJson(response, {}, 204);
      return;
    }

    if (path === "/v1/auth/refresh" && method === "POST") {
      sendJson(response, {
        access_token: fakeAccessToken(["operator"]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/auth/me" && method === "GET") {
      sendJson(response, {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Ada Markets",
        email: "ada@example.com",
        email_verified: true,
        id: userId,
        kyc_status: "verified",
        roles: ["operator"],
      });
      return;
    }

    if (path === "/v1/notifications" && method === "GET") {
      sendJson(response, {
        notifications: [],
        page: 1,
        page_size: 20,
        total: 0,
        unread_count: 0,
      });
      return;
    }

    if (path === "/v1/library" && method === "GET") {
      sendJson(response, {
        items: [],
        page: 1,
        page_size: 25,
        total: 0,
      });
      return;
    }

    if (path === `/v1/explore/frameworks/${frameworkId}` && method === "GET") {
      sendJson(response, frameworkDetail());
      return;
    }

    if (path === `/v1/explore/frameworks/${frameworkId}/related` && method === "GET") {
      sendJson(response, []);
      return;
    }

    if (path === "/v1/orgs/mine" && method === "GET") {
      sendJson(response, {
        organizations: [
          {
            capabilities: { operator: "active" },
            org: {
              country: "US",
              id: orgId,
              name: "Acme",
              slug: "acme",
              type: "company",
            },
            role: "admin",
          },
        ],
      });
      return;
    }

    if (path === `/v1/financials/purchase/${frameworkId}` && method === "POST") {
      selfPurchaseCalls += 1;
      sendJson(response, {
        client_secret: "pi_self_secret",
        provider: "stripe",
        transaction_id: "tx-self-1",
      });
      return;
    }

    if (path === `/v1/orgs/${orgId}/frameworks/${frameworkId}/purchase` && method === "POST") {
      orgPurchaseCalls += 1;
      lastOrgPurchaseBody = await readJsonBody(request);
      sendJson(response, {
        client_secret: "pi_org_secret",
        provider: "stripe",
        transaction_id: "tx-org-1",
      });
      return;
    }

    sendJson(response, { detail: `Unhandled stub route: ${method} ${path}` }, 404);
  });

  await new Promise<void>((resolve) => {
    backendServer?.listen(8000, "127.0.0.1", () => resolve());
  });
}

/**
 * Stop the local stub backend after the spec completes.
 */
async function stopBackendStub(): Promise<void> {
  if (!backendServer) {
    return;
  }
  await new Promise<void>((resolve, reject) => {
    backendServer?.close((error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
  backendServer = null;
}

test.describe("Org framework pricing", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test.beforeAll(async () => {
    await startBackendStub();
  });

  test.afterAll(async () => {
    await stopBackendStub();
  });

  test("an eligible org buyer sees the org price and uses the org purchase route", async ({
    context,
    page,
  }) => {
    await seedSessionHint(context, ["operator"]);

    await page.goto(`/explore/${frameworkId}`);

    await expect(page.getByText("Organizational")).toBeVisible();
    await expect(page.getByText("$900")).toBeVisible();

    await page.getByRole("link", { name: "License Framework" }).click();
    await expect(page).toHaveURL(new RegExp(`/checkout/${frameworkId}$`));

    await expect(page.getByText("Purchase as")).toBeVisible();
    await page.getByLabel("Acme").click();
    await expect(page.getByText("$900")).toBeVisible();

    await page.getByRole("button", { name: "Start checkout" }).click();

    await expect
      .poll(() => ({
        body: lastOrgPurchaseBody,
        orgPurchaseCalls,
        selfPurchaseCalls,
      }))
      .toEqual({
        body: { license_type: "organizational" },
        orgPurchaseCalls: 1,
        selfPurchaseCalls: 0,
      });
  });
});
