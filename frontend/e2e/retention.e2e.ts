import { test, expect, type Page } from "@playwright/test";

import { signInAsStaff } from "./helpers";

// v11c retention-scoring — admin cohort filter + bulk-send end-to-end.
//
// Preconditions seeded by `python manage.py seed_data` (extended in v11c
// to seed 9 cohort customers across active/at_risk/dormant/lost + one
// dormant-with-sms_opt_out — and then run `recompute_retention` so the
// fixtures carry their derived cohort labels by the time the test runs).
//
// The fixtures live on PlayDesk Flagship, so the admin store-switcher
// is pinned to that store at the top of each test.

const FLAGSHIP_SLUG = "playdesk-flagship";

async function ensureFlagship(page: Page): Promise<void> {
  const switcher = page.getByTestId("store-switcher");
  if ((await switcher.count()) === 0) return;
  const flagshipTab = switcher.getByRole("tab", { name: /Flagship/ });
  const isSelected = (await flagshipTab.getAttribute("aria-selected")) === "true";
  if (!isSelected) {
    await flagshipTab.click();
    await page.waitForTimeout(800);
  }
}

test("cohort counts chip toolbar is populated after the sweeper", async ({ page }) => {
  await signInAsStaff(page);
  await page.goto("/admin/customers");
  await ensureFlagship(page);

  const toolbar = page.getByTestId("cohort-filter");
  await expect(toolbar).toBeVisible({ timeout: 10_000 });

  // After seed_data runs the sweeper, the dormant chip carries a >=3
  // count (2 plain dormant + 1 opted-out dormant from the v11c fixture).
  const dormantBtn = toolbar.locator('[data-cohort-button="dormant"]');
  await expect(dormantBtn).toBeVisible();
  const dormantText = (await dormantBtn.textContent()) ?? "";
  const match = dormantText.match(/Dormant \((\d+)\)/);
  expect(match, `expected "Dormant (N)" label, got: ${dormantText}`).not.toBeNull();
  const dormantCount = Number(match?.[1] ?? 0);
  expect(dormantCount).toBeGreaterThanOrEqual(3);
});

test("filter by Dormant narrows the visible customer list", async ({ page }) => {
  await signInAsStaff(page);
  await page.goto("/admin/customers");
  await ensureFlagship(page);

  await page.locator('[data-cohort-button="dormant"]').click();
  // Wait for the post-filter refetch — the count chip in the card header
  // updates with the dormant subset.
  await page.waitForTimeout(800);

  // Every visible cohort chip on a row must read "Dormant".
  const rowCohortChips = page.locator(".pd-tr--row [data-testid='cohort-chip']");
  const count = await rowCohortChips.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(rowCohortChips.nth(i)).toHaveAttribute("data-cohort", "dormant");
  }
});

test("bulk-send fires re-engagement and reports skipped opt-outs", async ({ page }) => {
  await signInAsStaff(page);
  await page.goto("/admin/customers");
  await ensureFlagship(page);

  await page.locator('[data-cohort-button="dormant"]').click();
  await page.waitForTimeout(800);

  // Auto-accept the JS confirm() dialog the page raises before posting.
  page.once("dialog", async (dialog) => {
    await dialog.accept();
  });

  await page.locator('[data-testid="cohort-bulk-send"]').click();

  // The toast confirms how many were sent / skipped. With the seeded
  // dormant set (2 plain + 1 opted-out) we expect at least one skip.
  const toast = page.locator('[data-testid="cohort-bulk-toast"]');
  await expect(toast).toBeVisible({ timeout: 15_000 });
  const toastText = (await toast.textContent()) ?? "";
  expect(toastText).toMatch(/Sent to \d+ customers, skipped \d+/);

  // Parse the skipped count and assert at least one skip (the opt-out).
  const skipMatch = toastText.match(/skipped (\d+)/);
  const skipped = Number(skipMatch?.[1] ?? 0);
  expect(skipped).toBeGreaterThanOrEqual(1);
});
