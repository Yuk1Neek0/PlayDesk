import { test, expect, type Page } from "@playwright/test";

import { signInAsStaff } from "./helpers";

// J1 — a customer completes a manual booking through the UI.
// J2 — the time picked on `/s/<slug>/book` is the time shown on `/admin`
//      (the timezone regression: a 10:00 pick must not surface as 22:00).
//
// Phase 2 design refresh: `/` is now a hub, not a redirect, so the
// flow lands on `/s/playdesk-flagship/book` directly here.

/** Click date cells until the slot grid offers a bookable hour; return it. */
async function pickFirstFreeSlot(page: Page): Promise<string> {
  const dates = page.locator("button.pd-date-cell");
  const count = await dates.count();
  for (let i = 0; i < count; i++) {
    await dates.nth(i).click();
    // Let the availability request for this date settle.
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

test("manual booking: pick a slot, confirm, and verify the time in admin", async ({ page }) => {
  const customer = `Playwright ${Date.now()}`;

  await page.goto("/s/playdesk-flagship/book");
  await expect(page.locator("button.pd-rcard").first()).toBeVisible();

  // Step 1 — first resource.
  await page.locator("button.pd-rcard").first().click();

  // Step 3 — shortest duration first, so a free hour is easy to find.
  await page.locator("button.pd-seg-item").first().click();

  // Step 2/3 — find a date with a free slot and pick it.
  const slot = await pickFirstFreeSlot(page);
  expect(slot, "no free slot on any date in the picker — availability is broken").not.toBe("");

  // Step 4 — fill the form and confirm.
  await page.locator("input.pd-input").first().fill(customer);
  await page.locator("input.pd-input").nth(1).fill("+1 416 555 0188");
  await page.getByRole("button", { name: /Confirm booking/ }).click();

  // The confirmation view echoes the picked time back.
  await expect(page.getByRole("heading", { name: /See you at PlayDesk/ })).toBeVisible();
  await expect(page.getByText(new RegExp(`${slot}\\s*[–-]`))).toBeVisible();

  // J2 — sign in as staff and confirm /admin shows the SAME start hour.
  await signInAsStaff(page);

  const row = page.locator(".pd-tr", { hasText: customer }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
  await expect(
    row,
    `admin shows a different time than the ${slot} that was booked`,
  ).toContainText(slot);
});
