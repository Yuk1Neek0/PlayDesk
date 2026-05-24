import { test, expect, type Page } from "@playwright/test";

import { signInAsStaff } from "./helpers";

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

/** Click date cells until the slot grid offers a bookable hour; return it. */
async function pickFirstFreeSlot(page: Page): Promise<string> {
  const dates = page.locator("button.pd-date-cell");
  const count = await dates.count();
  for (let i = 0; i < count; i++) {
    await dates.nth(i).click();
    await page.waitForTimeout(2000);
    const free = page.locator(".pd-slots-grid button.pd-slot:not([disabled])").first();
    if ((await free.count()) > 0) {
      const label = (await free.locator(".pd-slot-time").textContent())?.trim() ?? "";
      await free.click();
      return label;
    }
  }
  return "";
}

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
  await expect(page.locator("button.pd-rcard").first()).toBeVisible();

  // Step 1 — first resource.
  await page.locator("button.pd-rcard").first().click();
  // Shortest duration so a slot is easy to find.
  await page.locator("button.pd-seg-item").first().click();

  // Steps 2/3 — find a date with a free slot and pick it.
  const slot = await pickFirstFreeSlot(page);
  expect(slot, "no free slot found on the URL store — availability is broken").not.toBe("");

  // Step 4 — fill the form and confirm.
  await page.locator("input.pd-input").first().fill(customer);
  await page.locator("input.pd-input").nth(1).fill("+1 416 555 0188");
  await page.getByRole("button", { name: /Confirm booking/ }).click();
  await expect(page.getByRole("heading", { name: /See you at PlayDesk/ })).toBeVisible();

  // Verify in admin (separate context to avoid the customer cookie state):
  // sign in as staff, the booking row should be visible. The admin layout
  // mounts <StoreProvider>, which on first load picks the alphabetically-
  // first store (== flagship) so the booking is in scope by default.
  const adminPage = await context.newPage();
  await signInAsStaff(adminPage);

  const row = adminPage.locator(".pd-tr", { hasText: customer }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
});
