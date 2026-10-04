/**
 * Browser-level check that a Contributor can list a Framework free.
 *
 * QA reported being asked for a price after ticking the free toggle, and the
 * component tests could not have caught that: they submit the form directly
 * because jsdom does not run HTML constraint validation, so the `required`
 * attribute on the amount field is never exercised there.
 */
import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

import { mockSessionBootstrap } from "./helpers/authenticated-shell";

const apiOrigin = "http://127.0.0.1:8000";
const appOrigin = "http://127.0.0.1:3100";
const sessionHintSecret = "auracles-e2e-secret";
const contributorId = "00000000-0000-4000-8000-000000000002";

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

test("ticking Free creates the draft without asking for a price", async ({
  context,
  page,
}) => {
  await context.addCookies([
    { domain: "127.0.0.1", name: "session_hint", path: "/", value: sessionHintValue() },
  ]);
  let created: Record<string, unknown> | null = null;
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const req = route.request();
    const headers = {
      "access-control-allow-origin": appOrigin,
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "*",
    };
    if (req.method() === "OPTIONS") {
      await route.fulfill({ status: 204, body: "", headers });
      return;
    }
    if (new URL(req.url()).pathname === "/v1/frameworks" && req.method() === "POST") {
      created = JSON.parse(req.postData() ?? "{}");
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers,
        body: JSON.stringify({ id: "00000000-0000-4000-8000-000000000031" }),
      });
      return;
    }
    // Anything else (session bootstrap, taxonomy) belongs to the handler
    // registered before this one.
    await route.fallback();
  });

  await mockSessionBootstrap(page, { roles: ["contributor"] });

  await page.goto("/dashboard/frameworks/new");
  await page.getByLabel("Framework Title").fill("Free Rollout Runbook");
  await page.getByLabel("Description").fill("Rollout sequencing, offered free.");
  await page.getByLabel("Sector").selectOption({ index: 1 });
  await page.getByLabel("Industry").selectOption({ index: 1 });
  await page.getByLabel("Function").selectOption({ index: 1 });
  await page.getByLabel("Category").selectOption({ index: 1 });
  await page.getByLabel("Organization Size").selectOption({ index: 1 });
  await page.getByLabel("Single user").check();

  // The whole point: no price typed, just the toggle.
  await page.getByLabel(/offer this framework free/i).check();
  await page.getByRole("button", { name: "Create draft" }).click();

  await expect.poll(() => created, { timeout: 10_000 }).not.toBeNull();
  expect(created).toMatchObject({ pricing: { price: "0.00" } });
});

