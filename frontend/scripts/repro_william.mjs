import { chromium } from "@playwright/test";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on("console", msg => {
    console.log(`[BROWSER CONSOLE] ${msg.type().toUpperCase()}: ${msg.text()}`);
  });

  console.log("Navigating to login page...");
  await page.goto("http://localhost:3000/login");
  
  console.log("Filling form fields...");
  await page.fill('input[name="email"]', "williamikeji@gmail.com");
  await page.fill('input[name="password"]', "StrongerPass123!");
  
  console.log("Clicking login button...");
  await page.click('button[type="submit"]');
  
  console.log("Waiting 3 seconds...");
  await page.waitForTimeout(3000);
  
  console.log("Current URL:", page.url());

  console.log("Navigating to project page...");
  await page.goto("http://localhost:3000/projects/3a083dee-ce8e-4153-9739-caf9f591cbbe");

  console.log("Waiting 4 seconds for workspace to load...");
  await page.waitForTimeout(4000);

  console.log("Final URL:", page.url());

  await page.screenshot({ path: "/Users/a0000/.gemini/antigravity-ide/brain/259bcd46-c006-440a-ab23-cd9d12a8723e/scratch/repro_william.png" });
  console.log("Screenshot saved.");
  
  await browser.close();
})();
