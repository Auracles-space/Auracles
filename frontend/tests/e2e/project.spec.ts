/**
 * Browser-level Project flow coverage for Phase 4a Slice 12.
 *
 * Backend state transitions remain covered by FastAPI integration tests. This
 * browser test verifies the generated-client Project shell can drive the full
 * operator/contributor workflow against the public REST contract.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const projectId = "00000000-0000-4000-8000-000000000401";
const proposalId = "00000000-0000-4000-8000-000000000402";
const milestoneId = "00000000-0000-4000-8000-000000000403";
const deliverableId = "00000000-0000-4000-8000-000000000404";

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
 * Create a signed session hint accepted by auth middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["operator", "contributor"],
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
 * Return the mutable Project read model used by mocked responses.
 */
function project(status = "open", milestonePlanStatus = "draft") {
  return {
    accepted_proposal_id: status === "open" ? null : proposalId,
    budget_max: "2000.00",
    budget_min: "1000.00",
    category: "operations",
    closed_at: null,
    created_at: "2026-06-10T00:00:00Z",
    currency: "USD",
    deadline: "2026-08-01",
    delivered_at: null,
    description: "Build a procurement operating model for regional rollout.",
    expires_at: "2026-07-10T00:00:00Z",
    id: projectId,
    milestone_plan_status: milestonePlanStatus,
    operator_id: "00000000-0000-4000-8000-000000000011",
    required_deliverables: [
      {
        description: "Implementation guide and supporting templates.",
        name: "Implementation playbook",
      },
    ],
    status,
    title: "Procurement Playbook",
    updated_at: "2026-06-10T00:00:00Z",
  };
}

/**
 * Install mocked Project API routes.
 */
async function mockProjectApi(page: Page): Promise<void> {
  let currentProject = project();
  let proposals: unknown[] = [];
  let milestones: unknown[] = [];
  let messages: unknown[] = [];

  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/auth/me") {
      await fulfillJson(route, {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Test User",
        email: "test@example.com",
        email_verified: true,
        id: "00000000-0000-4000-8000-000000000001",
        kyc_status: "verified",
        roles: ["operator", "contributor"],
      });
      return;
    }

    if (path === "/v1/auth/refresh") {
      await fulfillJson(route, {
        access_token: fakeAccessToken(["operator", "contributor"]),
        expires_in: 900,
        token_type: "bearer",
      });
      return;
    }

    if (path === "/v1/projects" && request.method() === "GET") {
      const role = url.searchParams.get("role");
      await fulfillJson(route, {
        page: 1,
        page_size: 20,
        projects: role === "operator" ? [currentProject] : [project()],
        total: 1,
      });
      return;
    }

    if (path === "/v1/projects" && request.method() === "POST") {
      currentProject = project();
      await fulfillJson(route, currentProject, 201);
      return;
    }

    if (path === `/v1/projects/${projectId}`) {
      await fulfillJson(route, currentProject);
      return;
    }

    if (path === `/v1/projects/${projectId}/proposals` && request.method() === "GET") {
      await fulfillJson(route, { proposals });
      return;
    }

    if (
      path === `/v1/projects/${projectId}/proposals/mine` &&
      request.method() === "GET"
    ) {
      await fulfillJson(route, { proposals });
      return;
    }

    if (
      path === `/v1/projects/${projectId}/proposals` &&
      request.method() === "POST"
    ) {
      proposals = [
        {
          accepted_at: null,
          budget: "1500.00",
          contributor_id: "00000000-0000-4000-8000-000000000012",
          created_at: "2026-06-10T00:01:00Z",
          currency: "USD",
          deliverables: [
            {
              description: "Implementation playbook and rollout plan.",
              name: "Implementation playbook",
            },
          ],
          id: proposalId,
          project_id: projectId,
          scope: "I will deliver the operating model and rollout plan.",
          status: "pending",
          timeline_days: 30,
          withdrawn_at: null,
        },
      ];
      await fulfillJson(route, proposals[0], 201);
      return;
    }

    if (path === `/v1/projects/${projectId}/proposals/${proposalId}/accept`) {
      proposals = proposals.map((proposal) => ({
        ...(proposal as Record<string, unknown>),
        accepted_at: "2026-06-10T00:02:00Z",
        status: "accepted",
      }));
      currentProject = project("assigned", "draft");
      await fulfillJson(route, currentProject);
      return;
    }

    if (path === `/v1/projects/${projectId}/milestones` && request.method() === "GET") {
      await fulfillJson(route, { milestones });
      return;
    }

    if (
      path === `/v1/projects/${projectId}/milestones` &&
      request.method() === "POST"
    ) {
      milestones = [
        {
          approved_at: null,
          budget: "1500.00",
          created_at: "2026-06-10T00:03:00Z",
          currency: "USD",
          description: "Build the approved operating model.",
          due_date: null,
          escrow_id: null,
          funded_at: null,
          id: milestoneId,
          name: "Implementation",
          project_id: projectId,
          sequence: 1,
          status: "pending",
          submitted_at: null,
        },
      ];
      await fulfillJson(route, milestones[0], 201);
      return;
    }

    if (path === `/v1/projects/${projectId}/milestones/finalize`) {
      currentProject = project("assigned", "finalized");
      await fulfillJson(route, currentProject);
      return;
    }

    if (path === `/v1/projects/${projectId}/milestones/${milestoneId}/fund`) {
      milestones = milestones.map((m) => ({
        ...(m as Record<string, unknown>),
        status: "funded",
        funded_at: "2026-06-10T00:03:30Z",
      }));
      await fulfillJson(route, {
        client_secret: "pi_project_secret",
        provider: "stripe",
        transaction_id: "00000000-0000-4000-8000-000000000405",
      });
      return;
    }

    if (
      path ===
      `/v1/projects/${projectId}/milestones/${milestoneId}/deliverables`
    ) {
      milestones = milestones.map((m) => ({
        ...(m as Record<string, unknown>),
        status: "delivered",
        submitted_at: "2026-06-10T00:04:00Z",
      }));
      messages = [
        {
          body: null,
          created_at: "2026-06-10T00:04:00Z",
          file_keys: null,
          id: "00000000-0000-4000-8000-000000000406",
          project_id: projectId,
          scan_status: "visible",
          sender_id: null,
          system_event: "deliverable_submitted",
          system_payload: {
            deliverable_id: deliverableId,
            milestone_id: milestoneId,
          },
        },
      ];
      await fulfillJson(
        route,
        {
          approved_at: null,
          auto_approved: false,
          contributor_id: "00000000-0000-4000-8000-000000000012",
          created_at: "2026-06-10T00:04:00Z",
          description: "Approved implementation playbook and rollout guide.",
          file_keys: ["workspace/project/final-playbook.pdf"],
          id: deliverableId,
          milestone_id: milestoneId,
          name: "Final playbook",
          revision_notes: null,
          status: "submitted",
          submitted_at: "2026-06-10T00:04:00Z",
        },
        201,
      );
      return;
    }

    if (
      path ===
      `/v1/projects/${projectId}/milestones/${milestoneId}/deliverables/${deliverableId}/approve`
    ) {
      milestones = milestones.map((m) => ({
        ...(m as Record<string, unknown>),
        status: "approved",
        approved_at: "2026-06-10T00:05:00Z",
      }));
      await fulfillJson(route, {
        approved_at: "2026-06-10T00:05:00Z",
        auto_approved: false,
        contributor_id: "00000000-0000-4000-8000-000000000012",
        created_at: "2026-06-10T00:04:00Z",
        description: "Approved implementation playbook and rollout guide.",
        file_keys: ["workspace/project/final-playbook.pdf"],
        id: deliverableId,
        milestone_id: milestoneId,
        name: "Final playbook",
        revision_notes: null,
        status: "approved",
        submitted_at: "2026-06-10T00:04:00Z",
      });
      return;
    }

    if (path === `/v1/projects/${projectId}/messages` && request.method() === "GET") {
      await fulfillJson(route, { messages });
      return;
    }

    if (path === `/v1/projects/${projectId}/messages` && request.method() === "POST") {
      await fulfillJson(
        route,
        {
          body: "Implementation update posted.",
          created_at: "2026-06-10T00:06:00Z",
          file_keys: null,
          id: "00000000-0000-4000-8000-000000000407",
          project_id: projectId,
          scan_status: "visible",
          sender_id: "00000000-0000-4000-8000-000000000012",
          system_event: null,
          system_payload: null,
        },
        201,
      );
      return;
    }

    await fulfillJson(route, { detail: `Unhandled mocked Project route ${path}` }, 404);
  });
}

test("Operator and Contributor complete the Project workspace flow", async ({
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
  await mockProjectApi(page);

  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Commission and deliver custom work" })).toBeVisible();

  await page.getByRole("link", { name: "Post project" }).click();
  await page.getByLabel("Title").fill("Procurement Playbook");
  await page
    .getByRole("textbox", { exact: true, name: "Description" })
    .fill("Build a procurement operating model for regional rollout.");
  await page.getByLabel("Category").selectOption("operations");
  await page.getByLabel("Minimum budget").fill("1000.00");
  await page.getByLabel("Maximum budget").fill("2000.00");
  await page.getByLabel("Deliverable name").fill("Implementation playbook");
  await page
    .getByLabel("Deliverable description")
    .fill("Implementation guide and supporting templates.");

  const pastDate = new Date();
  pastDate.setDate(pastDate.getDate() - 1);
  const pastDateString = pastDate.toISOString().split("T")[0];
  await page.getByLabel("Deadline").fill(pastDateString);
  await expect(page.getByText("Deadline cannot be in the past.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Post project" })).toBeDisabled();
  await page.getByLabel("Deadline").fill("");

  await page.getByRole("button", { name: "Post project" }).click();

  await expect(page.getByRole("heading", { name: "Procurement Playbook" })).toBeVisible();
  await page
    .getByLabel("Proposal scope")
    .fill("I will deliver the operating model and rollout plan.");
  await page.getByRole("textbox", { name: "Budget", exact: true }).fill("1500.00");
  await page.getByRole("button", { name: "Submit proposal" }).click();
  await expect(page.getByText("Proposal submitted.")).toBeVisible();

  await page.getByRole("button", { name: "Accept proposal" }).click();
  await expect(page.getByText("Proposal accepted.")).toBeVisible();

  await page.getByRole("button", { name: "Add milestone" }).click();
  await expect(page.getByText("Milestone added.")).toBeVisible();

  await page.getByRole("button", { name: "Finalize plan" }).click();
  await expect(page.getByText("Milestone plan finalized.")).toBeVisible();

  await page.getByRole("button", { name: "Fund milestone" }).click();
  await expect(page.getByText("Milestone funding started.")).toBeVisible();

  await page.getByRole("button", { name: "Submit deliverable" }).click();
  await expect(page.getByText("Deliverable submitted.")).toBeVisible();

  await page.getByRole("button", { name: "Approve deliverable" }).click();
  await expect(page.getByText("Deliverable approved.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Publish as Framework" })).toBeVisible();
});
