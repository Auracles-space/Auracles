/**
 * Browser-level Contributor publish flow: create → upload → checks → publish.
 *
 * The test mocks client-side API calls at the network boundary with one
 * stateful framework record, so the UI drives the same status transitions the
 * backend pipeline produces (draft → pipeline_passed → published). Backend
 * publish gates, virus/PII pipeline, and versioning rules remain covered by
 * FastAPI integration tests.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";

const contributorId = "00000000-0000-4000-8000-000000000002";
const frameworkId = "00000000-0000-4000-8000-000000000031";
const artifactId = "00000000-0000-4000-8000-000000000032";

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
        roles: ["contributor"],
        totp_verified: true,
        user_id: contributorId,
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

type MutableFramework = {
  status:
    | "draft"
    | "submitted"
    | "processing"
    | "pipeline_passed"
    | "published";
  artifacts: unknown[];
};

/** One clean, fully-processed artifact row for the pipeline gate. */
function processedArtifact(): Record<string, unknown> {
  return {
    created_at: "2026-06-09T00:00:00Z",
    file_key: "frameworks/artifacts/runbook.pdf",
    file_size: 4096,
    framework_id: frameworkId,
    id: artifactId,
    mime_type: "application/pdf",
    name: "Delivery runbook.pdf",
    near_duplicate_blocked: false,
    pii_detected: false,
    pii_review_needed: false,
    pii_types_found: [],
    processing_status: "processed",
    rarity_score: "0.75",
    redaction_accepted: false,
    redaction_available: false,
    redaction_status: null,
    scan_status: "clean",
    similarity_notice: null,
    source_kind: "upload",
  };
}

function frameworkResponse(state: MutableFramework): Record<string, unknown> {
  return {
    category: "playbook",
    complexity: null,
    contributor_id: contributorId,
    contributor_org_id: null,
    created_at: "2026-06-09T00:00:00Z",
    description: "Rollout sequencing for platform launches.",
    function: "governance",
    id: frameworkId,
    industry: "fund_management",
    jurisdiction: null,
    lifecycle_stage: null,
    org_size: "mid_market",
    preview_artifact_id: null,
    pricing: {
      commercial_rights: null,
      currency: "USD",
      license_types: ["single_user"],
      org_price: null,
      price: "250.00",
      usage_restrictions: null,
    },
    published_at: state.status === "published" ? "2026-06-10T00:00:00Z" : null,
    sector: "private_equity",
    source_project_id: null,
    status: state.status,
    tags: [],
    title: "Technology Rollout Runbook",
    updated_at: "2026-06-09T00:00:00Z",
    version: "1.0.0",
  };
}

/**
 * Install the stateful Contributor publish API mocks.
 */
async function mockPublishApi(
  page: Page,
  state: MutableFramework,
): Promise<void> {
  await page.route(`${apiOrigin}/mock-s3`, async (route) => {
    await route.fulfill({
      headers: { "access-control-allow-origin": appOrigin },
      status: 204,
    });
  });
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (method === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }
    if (path === "/v1/frameworks" && method === "POST") {
      state.status = "draft";
      await fulfillJson(route, frameworkResponse(state), 201);
      return;
    }
    if (path === `/v1/frameworks/${frameworkId}` && method === "GET") {
      await fulfillJson(route, frameworkResponse(state));
      return;
    }
    if (path === `/v1/frameworks/${frameworkId}/artifacts` && method === "GET") {
      await fulfillJson(route, state.artifacts);
      return;
    }
    if (path === `/v1/frameworks/${frameworkId}/artifacts/upload-url`) {
      await fulfillJson(route, {
        artifact_key: "frameworks/artifacts/runbook.pdf",
        fields: { key: "frameworks/artifacts/runbook.pdf" },
        upload_url: `${apiOrigin}/mock-s3`,
      });
      return;
    }
    if (path === `/v1/frameworks/${frameworkId}/artifacts/confirm`) {
      state.artifacts = [processedArtifact()];
      await fulfillJson(route, processedArtifact(), 201);
      return;
    }
    if (path === `/v1/frameworks/${frameworkId}/submit`) {
      // The real pipeline runs asynchronously; the mock lands directly on
      // the passed state the publish gate requires.
      state.status = "pipeline_passed";
      await fulfillJson(route, frameworkResponse(state));
      return;
    }
    if (path === `/v1/frameworks/${frameworkId}/publish`) {
      state.status = "published";
      await fulfillJson(route, frameworkResponse(state));
      return;
    }
    await fulfillJson(
      route,
      { detail: `Unhandled mocked publish route: ${method} ${path}` },
      404,
    );
  });
}

test("Contributor creates, uploads, passes checks, and publishes", async ({
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
  const state: MutableFramework = { status: "draft", artifacts: [] };
  await mockPublishApi(page, state);
  await mockSessionBootstrap(page, { roles: ["contributor"] });

  await page.goto("/dashboard/frameworks/new");

  await page.getByLabel("Framework Title").fill("Technology Rollout Runbook");
  await page
    .getByLabel("Description")
    .fill("Rollout sequencing for platform launches.");
  await page.getByLabel("Sector").selectOption({ index: 1 });
  await page.getByLabel("Industry").selectOption({ index: 1 });
  await page.getByLabel("Function").selectOption({ index: 1 });
  await page.getByLabel("Category").selectOption({ index: 1 });
  await page.getByLabel("Organization Size").selectOption({ index: 1 });
  await page.getByLabel(/price/i).first().fill("250.00");
  await page.getByLabel("Single user").check();

  await page.getByRole("button", { name: "Create draft" }).click();
  await page.waitForURL(`**/dashboard/frameworks/${frameworkId}`);

  // Upload the artifact the publish gate requires.
  await page
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      buffer: Buffer.from("%PDF-1.4 delivery runbook"),
      mimeType: "application/pdf",
      name: "Delivery runbook.pdf",
    });
  await expect(page.getByText("Delivery runbook.pdf").first()).toBeVisible();

  // Run the publishing checks; the mocked pipeline passes immediately.
  await page.getByRole("button", { name: "Run publishing checks" }).click();
  const publishButton = page.getByRole("button", { name: /^Publish/ });
  await expect(publishButton).toBeVisible();

  await publishButton.click();
  await expect(page.getByText(/published/i).first()).toBeVisible();
});
