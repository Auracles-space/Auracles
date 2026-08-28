/**
 * Browser-level public Explore catalog checks.
 *
 * Explore is SSR (SEO-critical), so its fetches happen on the Next server
 * where Playwright's route interception cannot reach. This spec therefore
 * runs a stub API HTTP server on the backend port for the test's duration,
 * serving both the server-rendered catalog fetch and any browser-side calls.
 * Backend search/filter/pagination rules remain covered by FastAPI
 * integration tests.
 */
import { createServer, type Server } from "node:http";
import { URL } from "node:url";

import { expect, test } from "@playwright/test";

const apiPort = 8000;

const frameworkId = "00000000-0000-4000-8000-000000000021";

const catalogItem = {
  attestation_badge: null,
  average_review_score: null,
  category: "playbook",
  complexity: 3,
  contributor_id: "00000000-0000-4000-8000-000000000002",
  contributor_name: "Ada Contributor",
  contributor_org_id: null,
  contributor_reputation_score: null,
  contributor_slug: null,
  contributor_verification_level: null,
  currency: "USD",
  description: "Operator-ready controls for diligence workstreams.",
  function: "governance",
  id: frameworkId,
  industry: "fund_management",
  item_type: "framework",
  jurisdiction: "US",
  license_types: ["single_user", "team"],
  lifecycle_stage: "growth",
  org_size: "mid_market",
  owned: false,
  price: "250.00",
  published_at: "2026-06-09T00:00:00Z",
  rarity_score: "0.82",
  reputation: null,
  review_count: 0,
  sector: "private_equity",
  tags: ["diligence", "controls"],
  thumbnail_key: null,
  title: "Diligence Control Playbook",
  version: "1.0.1",
};

const filteredItem = {
  ...catalogItem,
  id: "00000000-0000-4000-8000-000000000022",
  sector: "technology",
  title: "Technology Rollout Runbook",
  description: "Rollout sequencing for platform launches.",
};

const frameworkDetail = {
  artifacts: [
    {
      created_at: "2026-06-09T00:00:00Z",
      file_size: 2048,
      id: "00000000-0000-4000-8000-000000000023",
      mime_type: "application/pdf",
      name: "Implementation playbook.pdf",
    },
  ],
  category: "playbook",
  complexity: 3,
  currency: "USD",
  description: "Operator-ready controls for diligence workstreams.",
  function: "governance",
  id: frameworkId,
  industry: "fund_management",
  jurisdiction: "US",
  license_types: ["single_user", "team"],
  lifecycle_stage: "growth",
  org_size: "mid_market",
  owned: false,
  preview_artifact_id: null,
  preview_url: null,
  price: "250.00",
  published_at: "2026-06-09T00:00:00Z",
  rarity_score: "0.82",
  sector: "private_equity",
  tags: ["diligence", "controls"],
  thumbnail_key: null,
  title: "Diligence Control Playbook",
  version: "1.0.1",
};

/** Requests the stub could not answer, surfaced on failure for fast triage. */
const unhandledPaths: string[] = [];

let server: Server;

test.beforeAll(async () => {
  server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", `http://127.0.0.1:${apiPort}`);
    const respond = (body: unknown, status = 200) => {
      response.writeHead(status, {
        "access-control-allow-credentials": "true",
        "access-control-allow-headers": "content-type,authorization",
        "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
        "access-control-allow-origin": "http://127.0.0.1:3100",
        "content-type": "application/json",
      });
      response.end(JSON.stringify(body));
    };

    if (request.method === "OPTIONS") {
      respond({}, 204);
      return;
    }
    if (url.pathname === "/v1/explore/catalog") {
      const sector = url.searchParams.get("sector");
      const items = sector === "technology" ? [filteredItem] : [catalogItem];
      respond({
        items,
        page: 1,
        page_size: 25,
        sort: "newest",
        total: items.length,
      });
      return;
    }
    if (url.pathname === `/v1/explore/frameworks/${frameworkId}`) {
      respond(frameworkDetail);
      return;
    }
    unhandledPaths.push(`${request.method} ${url.pathname}`);
    respond({ detail: "Unhandled mocked explore route." }, 404);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(apiPort, "127.0.0.1", resolve);
  });
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

test("visitor browses the catalog, filters it, and opens a framework", async ({
  page,
}) => {
  await page.goto("/explore");

  // SSR delivered the catalog: the card is in the initial document.
  await expect(
    page.getByText("Diligence Control Playbook").first(),
  ).toBeVisible();
  await expect(page.getByText("Ada Contributor").first()).toBeVisible();

  // Filtering re-queries the catalog with the sector applied.
  await page.goto("/explore?sector=technology");
  await expect(
    page.getByText("Technology Rollout Runbook").first(),
  ).toBeVisible();
  await expect(page.getByText("Diligence Control Playbook")).toHaveCount(0);

  // The detail page SSRs the full framework with its purchase CTA.
  await page.goto(`/explore/${frameworkId}`);
  await expect(
    page.getByRole("heading", { name: "Diligence Control Playbook" }),
  ).toBeVisible();
  await expect(page.getByText("Implementation playbook.pdf")).toBeVisible();
  await expect(page.getByText("$250").first()).toBeVisible();
  await expect(
    page.getByRole("link", { name: "License Framework" }),
  ).toBeVisible();
});
