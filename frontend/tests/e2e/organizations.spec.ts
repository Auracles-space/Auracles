/**
 * Browser-level checks for the organization owner's journey end to end.
 *
 * Backend rules stay covered by FastAPI tests. This spec drives the real
 * screens against a mocked API: create an organization and land on its
 * profile, invite and resend from the invitations tab, accept from the inbox,
 * transfer ownership through the step-up prompt, and close the organization
 * (blocked first, then with a reason).
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
 * §Decisions 2 and 4, §Slice A and B.
 */
import { createHmac } from "node:crypto";

import { expect, type BrowserContext, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const ownerId = "00000000-0000-4000-8000-000000000001";
const colleagueId = "00000000-0000-4000-8000-000000000002";
const orgId = "11111111-1111-4111-8111-111111111111";

type Route = Parameters<Parameters<Page["route"]>[1]>[0];

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** Signed session hint the middleware accepts for the given user. */
function sessionHintValue(userId: string): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        roles: ["contributor"],
        totp_verified: true,
        user_id: userId,
      },
      ["exp", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

/** Unsigned access token the client only decodes for claims. */
function fakeAccessToken(userId: string): string {
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(
    JSON.stringify({
      exp: Math.floor(Date.now() / 1000) + 900,
      iat: Math.floor(Date.now() / 1000),
      roles: ["contributor"],
      totp_verified: true,
      user_id: userId,
    }),
  );
  return `${header}.${payload}.`;
}

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    body: status === 204 ? "" : JSON.stringify(body),
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
 * Save a full-page screenshot when E2E_SHOTS names a directory.
 *
 * Off by default; used for visual review at desktop and phone widths
 * (E2E_VIEWPORT=375 shrinks the viewport first).
 */
async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.E2E_SHOTS;
  if (!dir) return;
  await page.screenshot({ fullPage: true, path: `${dir}/${name}.png` });
}

/** Mutable server state the mocks read so actions change what renders. */
type OrgState = {
  userId: string;
  orgCreated: boolean;
  kybStatus: string;
  invitations: Array<Record<string, unknown>>;
  received: Array<Record<string, unknown>>;
  stepUpActive: boolean;
  stepUpRefusals: number;
  resendCalls: string[];
  acceptCalls: string[];
  transferBodies: Array<Record<string, unknown>>;
  closeAttempts: number;
  closeBlocked: boolean;
  closeBodies: Array<Record<string, unknown> | null>;
  unhandled: string[];
};

function freshState(overrides: Partial<OrgState> = {}): OrgState {
  return {
    userId: ownerId,
    orgCreated: false,
    kybStatus: "unverified",
    invitations: [],
    received: [],
    stepUpActive: false,
    stepUpRefusals: 0,
    resendCalls: [],
    acceptCalls: [],
    transferBodies: [],
    closeAttempts: 0,
    closeBlocked: true,
    closeBodies: [],
    unhandled: [],
    ...overrides,
  };
}

function organization(slug = "kano-audit", name = "Kano Audit Partners") {
  return {
    id: orgId,
    slug,
    name,
    country: "NG",
    logo_key: null,
    logo_url: null,
    website: null,
    description: null,
    created_at: "2026-09-14T09:00:00Z",
    suspended_at: null,
    suspension_reason: null,
  };
}

function mineEntry(state: OrgState) {
  return {
    org: organization(),
    role: "owner",
    capabilities: {},
    capability_reasons: {},
    kyb_status: state.kybStatus,
    kyb_verified_at: null,
    member_count: 2,
    grants: {},
    nda_required: false,
    counts: { offers: 0, queue: 0, invitations: 0 },
  };
}

const members = [
  {
    id: "member-owner",
    user_id: ownerId,
    display_name: "Ada Okafor",
    email: "ada@kanoaudit.ng",
    role: "owner",
    joined_at: "2026-09-14T09:00:00Z",
    nda_signed: false,
  },
  {
    id: "member-colleague",
    user_id: colleagueId,
    display_name: "Tunde Bello",
    email: "tunde@kanoaudit.ng",
    role: "admin",
    joined_at: "2026-09-14T10:00:00Z",
    nda_signed: false,
  },
];

/** Invitation with an expiry relative to now, so the row copy stays stable. */
function invitation(id: string, email: string, status: string, expiresInDays: number) {
  return {
    id,
    email,
    role: "member",
    status,
    created_at: "2026-09-10T09:00:00Z",
    expires_at: new Date(Date.now() + expiresInDays * 86_400_000).toISOString(),
  };
}

async function mockOrgApi(page: Page, state: OrgState): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    // Session bootstrap.
    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(state.userId),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }
    if (path === "/v1/users/me") {
      await fulfillJson(route, {
        id: state.userId,
        email: state.userId === ownerId ? "ada@kanoaudit.ng" : "tunde@kanoaudit.ng",
        display_name: state.userId === ownerId ? "Ada Okafor" : "Tunde Bello",
        email_verified: true,
        kyc_status: "verified",
        roles: ["contributor"],
      });
      return;
    }
    if (path === "/v1/notifications") {
      await fulfillJson(route, { notifications: [], unread_count: 0, total: 0 });
      return;
    }

    // Step-up window: sensitive writes refuse until a code is verified.
    if (path === "/v1/auth/step-up" && method === "GET") {
      await fulfillJson(route, {
        active: state.stepUpActive,
        verified_until: state.stepUpActive ? new Date(Date.now() + 600_000).toISOString() : null,
      });
      return;
    }
    if (path === "/v1/auth/step-up" && method === "POST") {
      const body = request.postDataJSON() as { code?: string };
      if (body.code !== "123456") {
        await fulfillJson(route, { detail: "Invalid 2FA code." }, 422);
        return;
      }
      state.stepUpActive = true;
      await fulfillJson(route, { verified_until: new Date(Date.now() + 600_000).toISOString() });
      return;
    }

    // Organizations.
    if (path === "/v1/orgs/mine") {
      const entries = state.orgCreated && state.userId === ownerId ? [mineEntry(state)] : [];
      await fulfillJson(route, { organizations: entries });
      return;
    }
    if (path === "/v1/orgs" && method === "POST") {
      const body = request.postDataJSON() as { slug: string; name: string };
      state.orgCreated = true;
      await fulfillJson(route, organization(body.slug, body.name), 201);
      return;
    }
    if (path === "/v1/org-invitations/received") {
      await fulfillJson(route, { invitations: state.received });
      return;
    }
    const accept = path.match(/^\/v1\/org-invitations\/received\/([^/]+)\/accept$/);
    if (accept && method === "POST") {
      state.acceptCalls.push(accept[1]);
      state.received = state.received.filter((item) => item.id !== accept[1]);
      await fulfillJson(route, { role: "member" });
      return;
    }

    const orgPrefix = `/v1/orgs/${orgId}`;
    if (path === `${orgPrefix}/nda`) {
      await fulfillJson(route, {
        required: false,
        current_version: "1.0",
        signed_version: null,
        signed_at: null,
      });
      return;
    }
    if (path === `${orgPrefix}/members` && method === "GET") {
      await fulfillJson(route, { members });
      return;
    }
    if (path === `${orgPrefix}/invitations` && method === "GET") {
      const status = url.searchParams.get("status") ?? "pending";
      const rows =
        status === "all"
          ? state.invitations
          : state.invitations.filter((item) => item.status === status);
      await fulfillJson(route, { invitations: rows });
      return;
    }
    if (path === `${orgPrefix}/invitations` && method === "POST") {
      const body = request.postDataJSON() as { email?: string };
      const created = invitation(`inv-${state.invitations.length + 1}`, body.email ?? "", "pending", 7);
      state.invitations.push(created);
      await fulfillJson(route, created, 201);
      return;
    }
    const resend = path.match(new RegExp(`^${orgPrefix}/invitations/([^/]+)/resend$`));
    if (resend && method === "POST") {
      state.resendCalls.push(resend[1]);
      state.invitations = state.invitations.map((item) =>
        item.id === resend[1] ? invitation(resend[1], String(item.email), "pending", 7) : item,
      );
      await fulfillJson(route, state.invitations.find((item) => item.id === resend[1]));
      return;
    }
    if (path === `${orgPrefix}/transfer-ownership` && method === "POST") {
      if (!state.stepUpActive) {
        state.stepUpRefusals += 1;
        await fulfillJson(route, { detail: { error_code: "step_up_required" } }, 403);
        return;
      }
      state.transferBodies.push(request.postDataJSON() as Record<string, unknown>);
      await fulfillJson(route, { detail: "Ownership transferred." });
      return;
    }
    if (path === orgPrefix && method === "DELETE") {
      state.closeAttempts += 1;
      const raw = request.postData();
      state.closeBodies.push(raw ? (JSON.parse(raw) as Record<string, unknown>) : null);
      if (state.closeBlocked) {
        await fulfillJson(
          route,
          {
            detail: {
              error_code: "org_has_active_capability",
              message: "Deactivate every capability before closing the organization.",
            },
          },
          409,
        );
        return;
      }
      state.orgCreated = false;
      await fulfillJson(route, {}, 204);
      return;
    }

    state.unhandled.push(`${method} ${path}`);
    await fulfillJson(route, { detail: `Unhandled mocked route ${method} ${path}` }, 404);
  });
}

async function signIn(page: Page, context: BrowserContext, state: OrgState): Promise<void> {
  const width = Number(process.env.E2E_VIEWPORT ?? 0);
  if (width > 0) {
    await page.setViewportSize({ height: 900, width });
  }
  await context.addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      name: "session_hint",
      path: "/",
      sameSite: "Lax",
      secure: false,
      value: sessionHintValue(state.userId),
    },
  ]);
  await mockOrgApi(page, state);
}

test.afterEach(async ({}, testInfo) => {
  // Unmocked calls are not failures (pages degrade gracefully) but they are
  // worth seeing when a screen starts fetching something new.
  const state = (testInfo as unknown as { orgState?: OrgState }).orgState;
  if (state && state.unhandled.length > 0) {
    testInfo.annotations.push({ type: "unmocked", description: state.unhandled.join(", ") });
  }
});

test("an owner creates an organization and can manage people before verification", async ({
  context,
  page,
}, testInfo) => {
  const state = freshState();
  (testInfo as unknown as { orgState: OrgState }).orgState = state;
  await signIn(page, context, state);

  await page.goto("/dashboard/organizations");
  await page.getByRole("button", { name: "Create Organization" }).first().click();

  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill("Kano Audit Partners");
  await dialog.getByLabel("Slug").fill("kano-audit");
  await expect(dialog.getByTestId("slug-preview")).toContainText("/orgs/kano-audit");
  await expect(dialog.getByText("The slug and country cannot be changed")).toBeVisible();
  await shot(page, "org-create-dialog");
  await dialog.getByRole("button", { name: "Create Organization" }).click();

  await expect(page).toHaveURL(new RegExp(`/dashboard/organizations/${orgId}$`));
  await expect(page.getByText("Public profile").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy public profile URL" })).toBeVisible();

  // Decision 2: people tabs are open while the business is unverified.
  await expect(page.getByRole("tab", { name: "Members", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Invitations", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Teams", exact: true })).toBeVisible();
  await shot(page, "org-profile");
});

test("an admin invites, filters to expired and resends; an invitee accepts from the inbox", async ({
  context,
  page,
}, testInfo) => {
  const state = freshState({
    orgCreated: true,
    invitations: [invitation("inv-expired", "chioma@kanoaudit.ng", "expired", -2)],
  });
  (testInfo as unknown as { orgState: OrgState }).orgState = state;
  await signIn(page, context, state);

  await page.goto(`/dashboard/organizations/${orgId}/invitations`);
  await page.getByLabel("Invite by email").fill("musa@kanoaudit.ng");
  await page.getByRole("button", { name: /Send|Invite/ }).last().click();

  await expect(page.getByText("musa@kanoaudit.ng")).toBeVisible();
  await expect(page.getByText(/Expires in 7 days|Expires in 6 days/)).toBeVisible();

  await page.getByRole("radio", { name: "Expired" }).or(page.getByRole("button", { name: "Expired" })).first().click();
  await expect(page.getByText("chioma@kanoaudit.ng")).toBeVisible();
  await expect(page.getByText(/^Expired \d/)).toBeVisible();
  await shot(page, "org-invitations-expired");
  await page.getByRole("button", { name: /Resend/ }).first().click();
  await expect.poll(() => state.resendCalls).toEqual(["inv-expired"]);

  // The invitee, in a fresh session, accepts from the inbox.
  await context.clearCookies();
  state.userId = colleagueId;
  state.received = [
    {
      id: "inv-received",
      created_at: "2026-09-14T09:00:00Z",
      invited_by_name: "Ada Okafor",
      org: organization(),
      role: "member",
    },
  ];
  await context.addCookies([
    {
      domain: "127.0.0.1",
      httpOnly: false,
      name: "session_hint",
      path: "/",
      sameSite: "Lax",
      secure: false,
      value: sessionHintValue(colleagueId),
    },
  ]);
  await page.goto("/dashboard/organizations");
  await expect(page.getByText("Kano Audit Partners")).toBeVisible();
  await page.getByRole("button", { name: "Accept" }).click();
  await expect.poll(() => state.acceptCalls).toEqual(["inv-received"]);
});

test("an owner transfers ownership through step-up and closes the organization with a reason", async ({
  context,
  page,
}, testInfo) => {
  const state = freshState({ orgCreated: true, kybStatus: "verified" });
  (testInfo as unknown as { orgState: OrgState }).orgState = state;
  await signIn(page, context, state);

  await page.goto(`/dashboard/organizations/${orgId}/danger-zone`);

  // Transfer: the member list loads (Slice A fix) and the write asks for a code.
  await page.getByLabel("New Owner").selectOption("member-colleague");
  await page.getByRole("button", { name: "Transfer Ownership" }).click();
  const stepUp = page.getByRole("dialog").filter({ hasText: "Confirm it's you" });
  await stepUp.getByLabel("Authenticator code").fill("123456");
  await stepUp.getByRole("button", { name: "Verify" }).click();
  await expect.poll(() => state.transferBodies.length).toBe(1);
  expect(state.transferBodies[0]).toMatchObject({ new_owner_member_id: "member-colleague" });
  expect(state.stepUpRefusals).toBe(1);

  // Close: blocked while a capability is active, and the server says why.
  await page.goto(`/dashboard/organizations/${orgId}/danger-zone`);
  await page.getByRole("button", { name: "Close organization" }).click();
  const confirm = page.getByRole("dialog").filter({ hasText: "Close organization" });
  await expect(confirm.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
  await confirm.getByLabel("Confirmation phrase").fill("Close Kano Audit Partners");
  await confirm.getByRole("button", { name: "Close", exact: true }).click();
  await expect(
    page.getByText("Deactivate every capability before closing the organization."),
  ).toBeVisible();
  await shot(page, "org-close-blocked");

  // Once nothing is active the close goes through with the reason attached.
  state.closeBlocked = false;
  await page.getByRole("button", { name: "Close organization" }).click();
  const retry = page.getByRole("dialog").filter({ hasText: "Close organization" });
  await retry.locator("#close-reason").fill("Merged into Lagos Audit Partners.");
  await retry.getByLabel("Confirmation phrase").fill("Close Kano Audit Partners");
  await retry.getByRole("button", { name: "Close", exact: true }).click();

  await expect(page).toHaveURL(/\/dashboard\/organizations$/);
  expect(state.closeAttempts).toBe(2);
  expect(state.closeBodies[1]).toEqual({ reason: "Merged into Lagos Audit Partners." });
});
