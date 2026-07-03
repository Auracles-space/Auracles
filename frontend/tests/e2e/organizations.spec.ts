import { test, expect } from "@playwright/test";

test.describe("Organization Lifecycle E2E", () => {
  // Use a unique slug to avoid conflicts if run against a persistent DB
  const orgSlug = `acme-corp-${Date.now()}`;
  const orgName = "Acme Corp";
  const user1Email = "owner@example.com";
  const user2Email = "invitee@example.com";

  test("full organization lifecycle: create -> invite -> team -> suspend -> delete", async ({ page, request, context }) => {
    // ----------------------------------------------------
    // 1. Organization Creation (Owner)
    // ----------------------------------------------------
    
    // Assume user is logged in as user1 (mocked or via global setup)
    // Navigating to dashboard organizations
    await page.goto("/dashboard/organizations");
    
    // Create new organization
    await page.click("text=Create Organization");
    await page.fill('input[name="name"]', orgName);
    await page.fill('input[name="slug"]', orgSlug);
    await page.click('button:has-text("Create")');

    // Verify redirect to org dashboard
    await expect(page).toHaveURL(`/dashboard/organizations/${orgSlug}`);
    await expect(page.locator("h1")).toContainText("Organization Profile");

    // ----------------------------------------------------
    // 2. Invitation (Owner invites User2)
    // ----------------------------------------------------
    
    // Navigate to invitations tab
    await page.click("text=Invitations");
    
    // Invite member
    await page.fill('input[type="email"]', user2Email);
    await page.selectOption('select', { label: 'Member' });
    await page.click('button:has-text("Send Invitation")');
    
    // Verify invitation is in pending list
    await expect(page.locator(`text=${user2Email}`)).toBeVisible();
    await expect(page.locator("text=pending")).toBeVisible();

    // ----------------------------------------------------
    // 3. Team Assignment (Owner creates team)
    // ----------------------------------------------------
    
    // Navigate to teams tab
    await page.click("text=Teams");
    
    // Create a new team
    await page.fill('input[placeholder="Team Name"]', "Engineering");
    await page.fill('input[placeholder="Team Description"]', "Core engineers");
    await page.click('button:has-text("Create Team")');

    // Verify team is created
    await expect(page.locator("text=Engineering")).toBeVisible();

    // Note: Assuming user2 accepts invite in background or via API for the sake of team assignment
    // In a real E2E, we might open a new browser context for User2 to accept it.
    
    // ----------------------------------------------------
    // 4. Admin Suspension (Admin action)
    // ----------------------------------------------------
    
    // Navigate to admin organizations view
    await page.goto("/admin/organizations");
    
    // Search or find the created organization
    const orgRow = page.locator(`tr:has-text("${orgName}")`);
    await expect(orgRow).toBeVisible();
    
    // Suspend organization
    await orgRow.locator('button:has-text("Suspend")').click();
    await page.fill('textarea[placeholder="Reason for suspension"]', "Violation of TOS");
    await page.click('button:has-text("Confirm Suspension")');
    
    // Verify badge updates to suspended
    await expect(orgRow.locator("text=suspended")).toBeVisible();

    // Verify owner sees suspension banner
    await page.goto(`/dashboard/organizations/${orgSlug}`);
    await expect(page.locator("text=suspended")).toBeVisible();
    // Mutating actions should be disabled (e.g. Save buttons)
    await expect(page.locator('button:has-text("Save Changes")')).toBeDisabled();

    // ----------------------------------------------------
    // 5. Deletion (Owner Danger Zone)
    // ----------------------------------------------------
    
    // Navigate to Danger Zone
    await page.click("text=Danger Zone");
    
    // Initiate deletion
    await page.click('button:has-text("Deactivate Organization")');
    
    // Confirm deletion by typing slug
    await page.fill('input[placeholder="Enter organization slug"]', orgSlug);
    await page.click('button:has-text("Confirm Deactivation")');
    
    // Verify redirect to organizations list
    await expect(page).toHaveURL("/dashboard/organizations");
    // Verify org is no longer in the list
    await expect(page.locator(`text=${orgName}`)).not.toBeVisible();
  });
});
