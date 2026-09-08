/**
 * Drive the new role flow on staging in a real browser.
 *
 * qa.kyc@auracles.space is Contributor-only with verified KYC — exactly the
 * shape of the reported bug — so it exercises both halves: the onboarding page
 * must stop claiming the identity is unverified, and /settings/roles must be
 * able to add Operator.
 *
 * Run from inside frontend/:  node verify-roles.mjs
 */
import { chromium } from "@playwright/test";

const BASE = "https://staging.auracles.space";
const EMAIL = "qa.kyc@auracles.space";
const PASSWORD = process.env.QA_PW;

const browser = await chromium.launch();
const page = await browser.newPage();

const problems = [];
page.on("console", (msg) => {
  if (msg.type() === "error") problems.push(`console.error: ${msg.text()}`);
});
page.on("pageerror", (err) => {
  problems.push(`pageerror: ${err.message}\n${(err.stack || "").slice(0, 800)}`);
});
page.on("requestfailed", (req) => {
  problems.push(`requestfailed: ${req.url()} ${req.failure()?.errorText}`);
});

async function snapshot(label) {
  const text = (await page.locator("body").innerText()).replace(/\n{2,}/g, "\n");
  console.log(`\n===== ${label} =====\nurl: ${page.url()}\n${text.slice(0, 1400)}`);
}

await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForTimeout(5000);
console.log("after login, url =", page.url());

// 1. The page the tester was bounced to, with the blocker the backend reports.
await page.goto(
  `${BASE}/settings/onboarding?error_code=role_required&next=%2Fprojects%2Fnew`,
  { waitUntil: "networkidle" },
);
await page.waitForTimeout(2500);
await snapshot("onboarding, blocked on role");

// 2. The durable home for the change.
await page.goto(`${BASE}/settings/roles`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await snapshot("settings/roles before");

// 3. Actually add the role.
const operator = page.getByLabel(/Operator/);
if (await operator.count()) {
  await operator.first().check();
  await page.getByRole("button", { name: /add role/i }).click();
  await page.waitForTimeout(6000);
  await snapshot("settings/roles after adding Operator");
} else {
  console.log("\n!! Operator checkbox not offered");
}

console.log(`\n--- browser problems (${problems.length}) ---`);
for (const p of problems.slice(0, 12)) console.log(p + "\n");

await browser.close();
