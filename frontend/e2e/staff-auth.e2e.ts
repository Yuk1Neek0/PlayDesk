import { test, expect, type Page } from "@playwright/test";

// v10a staff-auth — proves the real Django session-login flow works
// end-to-end and that the localStorage spoof vector is dead. The
// `playdesk_staff` user is seeded by backend/core/management/commands/seed_data.py.

const STAFF_USERNAME = "playdesk_staff";
const STAFF_PASSWORD = "playdesk_staff_demo_pw";

async function signIn(page: Page): Promise<void> {
  await page.getByLabel("Username").fill(STAFF_USERNAME);
  await page.getByLabel("Password").fill(STAFF_PASSWORD);
  await page.getByRole("button", { name: /Sign in/ }).click();
}

test("Test 1 — login flow happy path", async ({ page }) => {
  await page.goto("/admin");
  // Redirect to /staff/login with ?next=/admin
  await expect(page).toHaveURL(/\/staff\/login/);
  await expect(page).toHaveURL(/next=/);

  await signIn(page);

  await expect(page).toHaveURL(/\/admin/, { timeout: 20_000 });
  await expect(page.getByTestId("staff-username")).toContainText(STAFF_USERNAME, {
    timeout: 20_000,
  });
});

test("Test 2 — wrong password shows inline error", async ({ page }) => {
  await page.goto("/staff/login");
  await page.getByLabel("Username").fill(STAFF_USERNAME);
  await page.getByLabel("Password").fill("definitely-wrong-password-xyz");
  await page.getByRole("button", { name: /Sign in/ }).click();

  await expect(page.getByRole("alert")).toContainText(/Invalid credentials/);
  // Still on the login page.
  await expect(page).toHaveURL(/\/staff\/login/);
});

test("Test 3 — logout clears the session", async ({ page }) => {
  await page.goto("/staff/login");
  await signIn(page);
  await expect(page).toHaveURL(/\/admin/, { timeout: 20_000 });

  // The admin layout sub-header carries the Logout button.
  await page.getByTestId("staff-logout").click();
  await expect(page).toHaveURL(/\/staff\/login/, { timeout: 10_000 });

  // Re-visiting /admin without a cookie bounces back to /staff/login.
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/staff\/login/);
});

test("Test 4 — deep-link to /admin/customers preserves the next= target", async ({
  page,
}) => {
  await page.goto("/admin/customers");
  await expect(page).toHaveURL(/\/staff\/login/);
  await expect(page).toHaveURL(/next=%2Fadmin%2Fcustomers/);

  await signIn(page);
  await expect(page).toHaveURL(/\/admin\/customers/, { timeout: 20_000 });
});

test("Test 5 — localStorage spoofing is dead (the headline assertion)", async ({
  page,
}) => {
  // Land on the public root so we have a same-origin context to write
  // localStorage from (the old vector that v10a exists to kill).
  await page.goto("/");
  await page.evaluate(() => {
    window.localStorage.setItem(
      "playdesk.user",
      JSON.stringify({ name: "fake", role: "staff" }),
    );
  });

  await page.goto("/admin");
  // The middleware + server-side session check return 401; the provider
  // redirects to /staff/login. localStorage cannot mint a Django session.
  await expect(page).toHaveURL(/\/staff\/login/, { timeout: 15_000 });
});
