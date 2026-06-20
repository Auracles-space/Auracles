import { chromium } from "@playwright/test";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  console.log("Navigating to login page...");
  try {
    await page.goto("http://localhost:3000/login", { timeout: 10000 });
  } catch (e) {
    console.error("Navigation failed:", e.message);
  }
  
  await page.waitForTimeout(2000);
  console.log("Current URL:", page.url());
  console.log("Page title:", await page.title());
  
  const content = await page.content();
  console.log("Body text contains email input?", content.includes("email"));
  
  await page.screenshot({ path: "/Users/a0000/.gemini/antigravity-ide/brain/259bcd46-c006-440a-ab23-cd9d12a8723e/scratch/login_page_debug.png" });
  console.log("Screenshot saved.");
  
  await browser.close();
})();
