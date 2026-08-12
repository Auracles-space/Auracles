/**
 * Browser-level Collection workflow coverage for Phase 5b-1 Slice 8.
 *
 * The test mocks API calls at the network boundary. Backend publish validation,
 * webhook minting, allocation math, and refund locking remain covered by
 * FastAPI integration tests.
 */
import { createHmac } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const collectionId = "00000000-0000-4000-8000-000000000300";
const validCollectionId = "00000000-0000-4000-8000-000000000301";
const transactionId = "00000000-0000-4000-8000-000000000390";

const frameworks = [
  {
    category: "playbook",
    created_at: "2026-06-11T00:00:00Z",
    currency: "USD",
    id: "00000000-0000-4000-8000-000000000311",
    price: "250.00",
    status: "published",
    title: "Diligence Control Playbook",
    updated_at: "2026-06-11T00:00:00Z",
    version: "1.0.0",
  },
  {
    category: "checklist",
    created_at: "2026-06-11T00:00:00Z",
    currency: "USD",
    id: "00000000-0000-4000-8000-000000000312",
    price: "300.00",
    status: "published",
    title: "Risk Register Checklist",
    updated_at: "2026-06-11T00:00:00Z",
    version: "1.0.0",
  },
  {
    category: "template",
    created_at: "2026-06-11T00:00:00Z",
    currency: "USD",
    id: "00000000-0000-4000-8000-000000000313",
    price: "350.00",
    status: "published",
    title: "Control Evidence Template",
    updated_at: "2026-06-11T00:00:00Z",
    version: "1.0.0",
  },
];

function base64Url(value: string): string {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Create a signed session hint accepted by middleware.
 */
function sessionHintValue(): string {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["contributor", "operator"],
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

type CollectionRow = {
  bundle_price: string;
  contributor_id: string;
  created_at: string;
  currency: string;
  description: string;
  id: string;
  members: Array<{
    currency: string;
    framework_id: string;
    price: string;
    status: string;
    title: string;
  }>;
  status: "draft" | "published" | "unpublished";
  title: string;
  updated_at: string;
};

/**
 * Return the contributor-facing Collection response shape.
 */
function collectionResponse(
  collection: CollectionRow,
): CollectionRow & { contributor_id: string } {
  return collection;
}

/**
 * Install mocked Collection, Library, and refund API routes.
 */
async function mockCollectionsApi(page: Page): Promise<void> {
  const collections: CollectionRow[] = [];
  let downloaded = false;
  let purchaseStatus = "completed";

  await page.route("https://s3.test/**", async (route) => {
    await route.fulfill({
      body: "downloaded",
      contentType: "text/plain",
      status: 200,
    });
  });

  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (request.method() === "OPTIONS") {
      await fulfillJson(route, {}, 204);
      return;
    }

    if (path === "/v1/frameworks" && request.method() === "GET") {
      await fulfillJson(route, frameworks);
      return;
    }

    if (path === "/v1/collections/mine" && request.method() === "GET") {
      await fulfillJson(route, { collections });
      return;
    }

    if (path === "/v1/collections" && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, string>;
      const collection: CollectionRow = {
        bundle_price: body.bundle_price,
        contributor_id: "00000000-0000-4000-8000-000000000001",
        created_at: "2026-06-11T00:00:00Z",
        currency: "USD",
        description: body.description,
        id: collections.length === 0 ? collectionId : validCollectionId,
        members: [],
        status: "draft",
        title: body.title,
        updated_at: "2026-06-11T00:00:00Z",
      };
      collections.unshift(collection);
      await fulfillJson(route, collectionResponse(collection), 201);
      return;
    }

    const addMemberMatch = path.match(/^\/v1\/collections\/([^/]+)\/members$/);
    if (addMemberMatch && request.method() === "POST") {
      const body = JSON.parse(request.postData() ?? "{}") as Record<string, string>;
      const collection = collections.find((item) => item.id === addMemberMatch[1]);
      const framework = frameworks.find((item) => item.id === body.framework_id);
      if (!collection || !framework) {
        await fulfillJson(route, { detail: "Not found." }, 404);
        return;
      }
      if (
        !collection.members.some(
          (member) => member.framework_id === framework.id,
        )
      ) {
        collection.members.push({
          currency: framework.currency,
          framework_id: framework.id,
          price: framework.price,
          status: framework.status,
          title: framework.title,
        });
      }
      await fulfillJson(route, collectionResponse(collection));
      return;
    }

    const publishMatch = path.match(/^\/v1\/collections\/([^/]+)\/publish$/);
    if (publishMatch && request.method() === "POST") {
      const collection = collections.find((item) => item.id === publishMatch[1]);
      if (!collection) {
        await fulfillJson(route, { detail: "Not found." }, 404);
        return;
      }
      const memberSum = collection.members.reduce(
        (sum, member) => sum + Number(member.price),
        0,
      );
      if (Number(collection.bundle_price) >= memberSum) {
        await fulfillJson(
          route,
          { detail: "Bundle price must be lower than member value." },
          422,
        );
        return;
      }
      collection.status = "published";
      await fulfillJson(route, collectionResponse(collection));
      return;
    }

    const removeMemberMatch = path.match(
      /^\/v1\/collections\/([^/]+)\/members\/([^/]+)$/,
    );
    if (removeMemberMatch && request.method() === "DELETE") {
      const collection = collections.find((item) => item.id === removeMemberMatch[1]);
      if (!collection) {
        await fulfillJson(route, { detail: "Not found." }, 404);
        return;
      }
      collection.members = collection.members.filter(
        (member) => member.framework_id !== removeMemberMatch[2],
      );
      await fulfillJson(route, collectionResponse(collection));
      return;
    }

    if (path === "/v1/library") {
      await fulfillJson(route, {
        items: frameworks.map((framework, index) => ({
          collection_id: index === 0 ? null : validCollectionId,
          currency: framework.currency,
          current_version: framework.version,
          expires_at: null,
          framework_id: framework.id,
          granted_at: "2026-06-11T00:00:00Z",
          license_id: `00000000-0000-4000-8000-00000000032${index}`,
          license_type: "team",
          price: framework.price,
          seats_total: 10,
          seats_used: 1,
          source: index === 0 ? "individual" : "collection",
          status: index === 0 || purchaseStatus === "completed" ? "active" : "revoked",
          thumbnail_key: null,
          title: framework.title,
          version_at_grant: framework.version,
        })),
        page: 1,
        page_size: 25,
        total: 3,
      });
      return;
    }

    const frameworkDetailMatch = path.match(/^\/v1\/explore\/frameworks\/([^/]+)$/);
    if (frameworkDetailMatch) {
      const framework = frameworks.find((item) => item.id === frameworkDetailMatch[1]);
      if (!framework) {
        await fulfillJson(route, { detail: "Not found." }, 404);
        return;
      }
      await fulfillJson(route, {
        ...framework,
        artifacts: [
          {
            created_at: "2026-06-11T00:00:00Z",
            file_size: 2048,
            id: `00000000-0000-4000-8000-00000000033${frameworks.indexOf(framework)}`,
            mime_type: "application/pdf",
            name: `${framework.title}.pdf`,
          },
        ],
        attestation_badge: null,
        average_review_score: null,
        complexity: 3,
        contributor_id: "00000000-0000-4000-8000-000000000001",
        contributor_name: "Mara Okafor",
        description: `${framework.title} implementation material.`,
        function: "governance",
        industry: "software",
        jurisdiction: "US",
        lifecycle_stage: "growth",
        license_types: ["team"],
        org_size: "mid_market",
        owned: false,
        preview_artifact_id: null,
        preview_url: null,
        published_at: "2026-06-11T00:00:00Z",
        rarity_score: "0.82",
        review_count: 0,
        sector: "technology",
        tags: ["controls"],
        thumbnail_key: null,
      });
      return;
    }

    const downloadMatch = path.match(
      /^\/v1\/frameworks\/([^/]+)\/artifacts\/([^/]+)\/download$/,
    );
    if (downloadMatch) {
      downloaded = true;
      await fulfillJson(route, {
        artifact_id: downloadMatch[2],
        download_url: "https://s3.test/downloaded.pdf",
        expires_in: 900,
        framework_id: downloadMatch[1],
        license_id: "00000000-0000-4000-8000-000000000321",
      });
      return;
    }

    if (path === "/v1/financials/purchases" && request.method() === "GET") {
      await fulfillJson(route, {
        items: [
          {
            amount: "700.00",
            currency: "USD",
            framework_id: validCollectionId,
            framework_title: "Diligence Control Collection",
            license_id: "00000000-0000-4000-8000-000000000321",
            license_type: "team",
            provider: "stripe",
            purchased_at: "2026-06-11T00:00:00Z",
            status: purchaseStatus,
            transaction_id: transactionId,
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      });
      return;
    }

    if (path === `/v1/financials/purchases/${transactionId}/refund`) {
      if (downloaded) {
        await fulfillJson(
          route,
          { detail: "Purchases with artifact downloads cannot be refunded." },
          422,
        );
        return;
      }
      purchaseStatus = "refunded";
      await fulfillJson(route, {
        provider: "stripe",
        refund_id: "re_collection_123",
        status: "refunded",
        transaction_id: transactionId,
      });
      return;
    }

    await fulfillJson(route, { detail: "Unhandled mocked collection route." }, 404);
  });
}

/**
 * Add one Framework member through the Collection builder and wait for the API.
 */
async function addFrameworkToActiveBundle(
  page: Page,
  frameworkId: string,
): Promise<void> {
  const memberSelect = page.getByRole("combobox").last();
  await expect(memberSelect.locator(`option[value="${frameworkId}"]`)).toHaveCount(1);
  await memberSelect.selectOption(frameworkId);
  await expect(page.getByRole("button", { name: "Add to bundle" })).toBeEnabled();
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/v1/collections/") &&
        response.url().endsWith("/members") &&
        response.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Add to bundle" }).click(),
  ]);
}

test("Contributor builds a Collection and Operator sees/refunds collection licenses", async ({
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
  await mockCollectionsApi(page);
  await mockSessionBootstrap(page);

  await page.goto("/dashboard/collections");
  await page.getByPlaceholder("Collection title").fill("Overpriced Collection");
  await page.getByPlaceholder("Describe the bundle").fill("Invalid bundle.");
  await page.getByPlaceholder("Bundle price, USD").fill("1000.00");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(
    page.getByRole("heading", { name: "Overpriced Collection" }),
  ).toBeVisible();
  for (const framework of frameworks) {
    await addFrameworkToActiveBundle(page, framework.id);
  }
  await page.getByRole("button", { name: "Publish bundle" }).click();
  await expect(page.getByText("Collection update failed.")).toBeVisible();

  await page.getByPlaceholder("Collection title").fill("Diligence Control Collection");
  await page
    .getByPlaceholder("Describe the bundle")
    .fill("Discounted diligence controls.");
  await page.getByPlaceholder("Bundle price, USD").fill("700.00");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(
    page.getByRole("heading", { name: "Diligence Control Collection" }),
  ).toBeVisible();
  for (const framework of frameworks) {
    await addFrameworkToActiveBundle(page, framework.id);
  }
  await page.getByRole("button", { name: "Publish bundle" }).click();
  await expect(page.getByText("Published").first()).toBeVisible();

  await page.goto("/library");
  await expect(page.getByText("Diligence Control Playbook").first()).toBeVisible();
  await expect(page.getByText("Risk Register Checklist").first()).toBeVisible();
  await expect(page.getByText("Control Evidence Template").first()).toBeVisible();
  await expect(page.getByText("Source Collection").first()).toBeVisible();

  await page.getByRole("button", { name: "Refund" }).click();
  await expect(page.getByText("Refunded")).toBeVisible();
});

test("Operator download blocks Collection refund", async ({ context, page }) => {
  await context.addCookies([
    {
      domain: "127.0.0.1",
      name: "session_hint",
      path: "/",
      value: sessionHintValue(),
    },
  ]);
  await mockCollectionsApi(page);
  await mockSessionBootstrap(page);
  await page.goto("/library");

  await Promise.all([
    page.waitForURL("https://s3.test/**"),
    page
      .getByRole("button", { name: "Diligence Control Playbook.pdf Download" })
      .click(),
  ]);
  await page.goto("/library");
  await page.getByRole("button", { name: "Refund" }).click();
  await expect(
    page.getByText("Purchases with artifact downloads cannot be refunded."),
  ).toBeVisible();
});
