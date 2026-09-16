/**
 * Attestation request → report, browser-level (slice 3).
 *
 * The backend rules (refund on withdraw, release statuses, notifications)
 * are covered by FastAPI tests. This spec proves the requestor pages, the
 * attestor org's offers tab and the review workspace render the new states
 * and call the generated API surface, against a mocked API.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const userId = "00000000-0000-4000-8000-000000000001";
const roles = ["contributor", "operator", "attestor"];

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        roles,
        totp_verified: true,
        user_id: userId,
      },
      ["exp", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret)
    .update(payload)
    .digest("base64url");
  return `${payload}.${signature}`;
}

function fakeAccessToken(): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
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
  return `${header}.${payload}.`;
}

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

const inTwoDays = new Date(Date.now() + 2 * 24 * 3600 * 1000).toISOString();
const inThirtyHours = new Date(Date.now() + 30 * 3600 * 1000).toISOString();

/**
 * Build a requestor-visible attestation.
 *
 * @param overrides - Fields to override on the base row.
 */
function attestation(overrides: Record<string, unknown>) {
  return {
    id: "att-1",
    target_type: "framework",
    target_id: "fw-1",
    target_title: "Clinical audit framework",
    requestor_id: userId,
    attestor_org_id: null,
    attestor_org_name: null,
    status: "offered",
    outcome: null,
    review_type: "quality",
    brief: {
      what_it_does: "Structures clinical audits.",
      use_case: "Hospital quality teams.",
      jurisdiction: "NG",
      focus_areas: "Data handling",
      desired_outcome: "An independent quality opinion.",
    },
    requested_specializations: [],
    requested_jurisdictions: [],
    summary: null,
    scope: null,
    evidence_references: null,
    report_key: null,
    fee_amount: "300.00",
    currency: "USD",
    escrow_id: "esc-1",
    accepted_at: null,
    completion_due_at: null,
    issued_at: null,
    dispute_window_ends_at: null,
    closed_at: null,
    created_at: "2026-09-10T12:00:00Z",
    updated_at: "2026-09-10T12:00:00Z",
    open_clarification: false,
    dispute: null,
    ...overrides,
  };
}

type Mocks = {
  attestations: Record<string, Record<string, unknown>>;
  cancelled: string[];
  ratings: string[];
};

async function mockApi(page: Page, mocks: Mocks): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }
    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }
    if (path === "/v1/users/me") {
      await fulfillJson(route, {
        id: userId,
        email: "test@example.com",
        display_name: "Test User",
        email_verified: true,
        kyc_status: "verified",
        roles,
      });
      return;
    }
    if (path === "/v1/frameworks" && method === "GET") {
      await fulfillJson(route, [
        { id: "fw-1", title: "Clinical audit framework", status: "published" },
      ]);
      return;
    }
    if (path === "/v1/attestations" && method === "GET") {
      await fulfillJson(route, {
        attestations: Object.values(mocks.attestations),
      });
      return;
    }
    const detail = path.match(/^\/v1\/attestations\/([^/]+)$/);
    if (detail && method === "GET") {
      const row = mocks.attestations[detail[1]];
      if (!row) {
        await fulfillJson(route, { detail: "Attestation not found." }, 404);
        return;
      }
      await fulfillJson(route, row);
      return;
    }
    const cancel = path.match(/^\/v1\/attestations\/([^/]+)\/cancel$/);
    if (cancel && method === "POST") {
      mocks.cancelled.push(cancel[1]);
      mocks.attestations[cancel[1]] = {
        ...mocks.attestations[cancel[1]],
        status: "cancelled",
        closed_at: new Date().toISOString(),
      };
      await fulfillJson(route, mocks.attestations[cancel[1]]);
      return;
    }
    const rating = path.match(/^\/v1\/attestations\/([^/]+)\/rating$/);
    if (rating && method === "POST") {
      mocks.ratings.push(rating[1]);
      await fulfillJson(
        route,
        {
          id: "rating-1",
          attestation_id: rating[1],
          rated_by: userId,
          stars: 4,
          comment: null,
          created_at: new Date().toISOString(),
        },
        201,
      );
      return;
    }
    if (/^\/v1\/attestations\/[^/]+\/clarifications$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }
    if (/^\/v1\/attestations\/[^/]+\/report\/rubric$/.test(path)) {
      await fulfillJson(route, { scores: [] });
      return;
    }
    if (path === "/v1/orgs/mine") {
      await fulfillJson(route, {
        organizations: [
          {
            org: { id: "org-1", name: "Audit Ltd", slug: "audit-ltd" },
            role: "owner",
            capabilities: { attestor: "active" },
            kyb_status: "verified",
          },
        ],
      });
      return;
    }
    if (path === "/v1/orgs/org-1") {
      await fulfillJson(route, { id: "org-1", name: "Audit Ltd", slug: "audit-ltd", role: "owner" });
      return;
    }
    if (path === "/v1/orgs/org-1/attestation-offers") {
      await fulfillJson(route, {
        offers: [
          {
            offer_id: "offer-1",
            attestation_id: "att-3",
            target_type: "framework",
            target_id: "fw-1",
            target_title: "Clinical audit framework",
            status: "offered",
            cohort_index: 0,
            match_score: 0.873,
            offered_at: "2026-09-13T12:00:00Z",
            expires_at: inThirtyHours,
          },
        ],
      });
      return;
    }
    if (path === "/v1/orgs/org-1/attestations") {
      await fulfillJson(route, {
        attestations: [
          {
            id: "att-3",
            target_type: "framework",
            target_id: "fw-1",
            target_title: "Clinical audit framework",
            review_type: "quality",
            status: "in_review",
            outcome: null,
            reviewing_member_id: "mem-1",
            reviewing_member_name: "Alice Owner",
            assigned_to_me: true,
            accepted_at: "2026-09-12T12:00:00Z",
            completion_due_at: "2026-09-18T12:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      });
      return;
    }
    if (path === "/v1/orgs/org-1/members") {
      await fulfillJson(route, {
        members: [{ id: "mem-1", user_id: userId, role: "owner", name: "Alice Owner" }],
      });
      return;
    }
    await fulfillJson(route, { detail: `Unhandled mocked route ${method} ${path}` }, 404);
  });
}

/**
 * Save a full-page screenshot when E2E_SHOTS names a directory.
 *
 * Off by default; used for visual review of the slice at desktop and phone
 * widths (E2E_VIEWPORT=375 shrinks the viewport first).
 */
async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.E2E_SHOTS;
  if (!dir) return;
  await page.screenshot({ fullPage: true, path: `${dir}/${name}.png` });
}

async function signIn(page: Page): Promise<void> {
  const width = Number(process.env.E2E_VIEWPORT ?? 0);
  if (width > 0) {
    await page.setViewportSize({ height: 900, width });
  }
  await page.context().addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      sameSite: "Lax",
      secure: false,
      name: "session_hint",
      path: "/",
      value: sessionHintValue(),
    },
  ]);
}

test("requestor: deep link pins the framework; detail shows progress and withdraws with a refund", async ({
  page,
}) => {
  const mocks: Mocks = {
    attestations: { "att-1": attestation({}) },
    cancelled: [],
    ratings: [],
  };
  await signIn(page);
  await mockApi(page, mocks);

  await page.goto("/attestations?target=fw-1");
  await expect(page.getByText("Request an attestation")).toBeVisible();
  await expect(page.getByText("Clinical audit framework").first()).toBeVisible();
  await shot(page, "requestor-form");

  await page.goto("/attestations/att-1");
  await expect(page.getByRole("heading", { name: "Progress" })).toBeVisible();
  await expect(page.getByText("Offer sent")).toBeVisible();
  await expect(
    page.getByText("An attestor organization is considering your request. You can still withdraw."),
  ).toBeVisible();
  await shot(page, "requestor-detail-offered");
  await page.getByRole("button", { name: "Withdraw request" }).click();
  await expect(page.getByText("Withdraw this request?")).toBeVisible();
  await shot(page, "requestor-withdraw-dialog");
  await expect(
    page.getByText("Your request is cancelled and the fee is refunded to the original payment method."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Yes, withdraw" }).click();
  await expect(page.getByText("You withdrew this request.").first()).toBeVisible();
  expect(mocks.cancelled).toEqual(["att-1"]);
});

test("requestor: a released attestation names the attestor and can be rated once", async ({
  page,
}) => {
  const mocks: Mocks = {
    attestations: {
      "att-2": attestation({
        id: "att-2",
        status: "released",
        outcome: "approved",
        attestor_org_id: "org-1",
        attestor_org_name: "Audit Ltd",
        accepted_at: "2026-09-01T12:00:00Z",
        issued_at: "2026-09-05T12:00:00Z",
        closed_at: "2026-09-12T12:00:00Z",
        summary: "The framework meets the quality bar.",
        scope: "Full artifact review.",
      }),
    },
    cancelled: [],
    ratings: [],
  };
  await signIn(page);
  await mockApi(page, mocks);

  await page.goto("/attestations/att-2");
  await expect(page.getByText("Released").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit Ltd" })).toHaveAttribute(
    "href",
    "/attestors/org-1",
  );
  await expect(
    page.getByText("Complete. Rate the attestor and download your invoice."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Withdraw request" })).toHaveCount(0);
  await shot(page, "requestor-detail-released");
  await page.getByRole("button", { name: "4 stars" }).click();
  await page.getByRole("button", { name: "Submit rating" }).click();
  await expect(page.getByText("You have rated this attestation.")).toBeVisible();
  expect(mocks.ratings).toEqual(["att-2"]);
});

test("attestor org: offers show a match percentage and countdown; the workspace shows the due date", async ({
  page,
}) => {
  const mocks: Mocks = {
    attestations: {
      "att-3": attestation({
        id: "att-3",
        status: "in_review",
        attestor_org_id: "org-1",
        attestor_org_name: "Audit Ltd",
        accepted_at: "2026-09-12T12:00:00Z",
        completion_due_at: "2026-09-18T12:00:00Z",
        dispute_window_ends_at: inTwoDays,
      }),
    },
    cancelled: [],
    ratings: [],
  };
  await signIn(page);
  await mockApi(page, mocks);

  await page.goto("/dashboard/organizations/org-1/attestor/offers");
  await expect(page.getByText("87% match")).toBeVisible();
  await expect(page.getByText(/Expires in \d+ h/)).toBeVisible();
  await expect(page.getByText("Awaiting your response")).toBeVisible();
  await shot(page, "org-offers");
  await page.getByRole("button", { name: "Decline" }).click();
  await expect(page.getByText("Decline this offer?")).toBeVisible();
  await expect(page.getByLabel("Reason (optional)")).toBeVisible();
  await shot(page, "org-decline-dialog");
  await page.getByRole("button", { name: "Keep offer" }).click();

  await page.goto("/dashboard/organizations/org-1/attestations/att-3");
  await expect(page.getByText("Due 18 Sep 2026")).toBeVisible();
  await expect(page.getByText("In review").first()).toBeVisible();
  await expect(page.getByText("What the requestor asked for")).toBeVisible();
  await shot(page, "org-workspace");
});
