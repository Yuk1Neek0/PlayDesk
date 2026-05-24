import type { Page } from "@playwright/test";

// Shared e2e helpers (v10a staff-auth).
//
// The v10a real-login flow replaces the old "click 'Staff'" one-click
// demo button. Every admin-driving e2e test that previously did
//     await page.goto("/login");
//     await page.getByRole("button", { name: /Staff/ }).click();
// now goes through `signInAsStaff(page)` which exercises the real
// `/staff/login/` form with the seeded `playdesk_staff` credentials.

export const STAFF_USERNAME = "playdesk_staff";
export const STAFF_PASSWORD = "playdesk_staff_demo_pw";

/**
 * Sign into the admin app using the seeded staff credentials.
 *
 * Navigates to /staff/login and submits the real Django session
 * login form. Does not assert the post-login URL — callers do that
 * because some tests want to be on `/admin`, others on a deep link.
 */
export async function signInAsStaff(page: Page): Promise<void> {
  await page.goto("/staff/login");
  await page.getByLabel("Username").fill(STAFF_USERNAME);
  await page.getByLabel("Password").fill(STAFF_PASSWORD);
  await page.getByRole("button", { name: /Sign in/ }).click();
  // Wait until the form's full-page navigation completes so callers can
  // rely on subsequent goto()/asserts running against the new context.
  await page.waitForURL(/\/admin/, { timeout: 20_000 });
}
