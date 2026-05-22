import { test, expect } from "@playwright/test";

// J4 — the staff dashboard is gated. Each test gets a fresh browser context,
// so localStorage (the persisted session) starts empty.

test("admin redirects to login when not signed in", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);
});

test("the customer-facing nav does not expose Admin", async ({ page }) => {
  await page.goto("/");
  const nav = page.locator("nav.pd-nav");
  await expect(nav.getByRole("link", { name: "Book" })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Admin/ })).toHaveCount(0);
});

test("staff can sign in and reach the dashboard", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /Staff/ }).click();
  await expect(page).toHaveURL(/\/admin/);
  await expect(page.getByRole("heading", { name: /Tonight at PlayDesk/ })).toBeVisible();
  await expect(page.getByText("All bookings")).toBeVisible();
});

test("the staff session survives a page refresh", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /Staff/ }).click();
  await expect(page).toHaveURL(/\/admin/);

  await page.reload();
  await expect(page).toHaveURL(/\/admin/);
  await expect(page.getByRole("heading", { name: /Tonight at PlayDesk/ })).toBeVisible();
});

test("a customer cannot reach the dashboard", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /Customer/ }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);
});
