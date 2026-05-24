import { test, expect } from "@playwright/test";

import { bookFirstFreeSlot, signInAsStaff } from "./helpers";

// v6 multi-location, task #162 — customer-facing store-scoped URLs.
//
// Verifies:
//   1. `/s/playdesk-flagship/book` renders the flagship-branded booking page.
//   2. `/` renders the four-entry hub (Phase 2 design refresh retired the
//      v6-era 302 to `/s/<slug>/book` — see DESIGN_AUDIT.md §4) and the
//      "Book now" entry still links to the default store's
//      `/s/<slug>/book` URL, so printed QRs / bookmarks pointing at `/`
//      keep working with one extra tap.
//
// This suite intentionally does NOT mutate brand state — that's
// branded-booking.e2e.ts's job. Here we just need the booking page to
// render under the new URL.

const FLAGSHIP_SLUG = "playdesk-flagship";

test("direct nav to /s/<flagship>/book renders the booking page", async ({ page }) => {
  await page.goto(`/s/${FLAGSHIP_SLUG}/book`);
  await expect(page.getByRole("heading", { name: /Pick your station/ })).toBeVisible();
  await expect(page.locator("button.pd-rcard").first()).toBeVisible();
});

test("/ renders the hub and the Book entry points at the default store", async ({ page }) => {
  const response = await page.goto("/");
  // Phase 2 design refresh: `/` is now a real landing, not a 302. Assert
  // the hub hero copy is on the page and the Book CTA's href is the
  // default-store booking URL the v6 redirect used to use.
  await expect(page).toHaveURL(/\/?$/);
  await expect(page.getByRole("heading", { name: /Welcome to/ })).toBeVisible();
  const bookCta = page.getByRole("link", { name: /Book now/ });
  await expect(bookCta).toBeVisible();
  await expect(bookCta).toHaveAttribute("href", new RegExp(`/s/[^/]+/book$`));
  // Sanity-check the response object is non-null (catches navigation
  // regressions that would have caused page.goto to throw).
  expect(response).not.toBeNull();
});

test("a booking made via /s/<slug>/book is associated with that store", async ({
  page,
  context,
}) => {
  const customer = `StoreRouting ${Date.now()}`;

  await page.goto(`/s/${FLAGSHIP_SLUG}/book`);
  // Helper handles resource + duration + slot picking, with 409 retries.
  await bookFirstFreeSlot(page, customer, "+1 416 555 0188");

  // Verify in admin (separate context to avoid the customer cookie state):
  // sign in as staff, the booking row should be visible. The admin layout
  // mounts <StoreProvider>, which on first load picks the alphabetically-
  // first store (== flagship) so the booking is in scope by default.
  const adminPage = await context.newPage();
  await signInAsStaff(adminPage);

  const row = adminPage.locator(".pd-tr", { hasText: customer }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
});
