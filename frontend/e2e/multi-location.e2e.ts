import { test, expect, type Page } from "@playwright/test";

// v6 multi-location, task #163 — cross-store isolation invariant.
//
// The end-to-end payoff for the epic: switch stores in admin and see
// different data; book at one store and verify it doesn't show in the
// other. This is the first test in the suite that genuinely exercises
// multi-store behaviour; it catches "I forgot to scope this query"
// regressions in future PRs.
//
// Requires both seeded stores (`playdesk-flagship` + `playdesk-north`)
// — the integrity CI rebuilds from the branch and runs `seed_data`
// before this suite, so both stores are present.

const FLAGSHIP_SLUG = "playdesk-flagship";
const NORTH_SLUG = "playdesk-north";

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

test("cross-store isolation: book at North, only visible while admin is on North", async ({
  page,
  context,
}) => {
  const northCustomer = `MultiLocNorth ${Date.now()}`;

  // ── Admin: sign in and verify the StoreSwitcher exposes both stores ──
  await page.goto("/login");
  await page.getByRole("button", { name: /Staff/ }).click();
  await expect(page).toHaveURL(/\/admin/);

  const switcher = page.getByTestId("store-switcher");
  await expect(switcher).toBeVisible({ timeout: 10_000 });
  // Two chips: one per seeded store. (The exact labels track the seed
  // names: "PlayDesk Flagship" and "PlayDesk North · Toronto".)
  const chips = switcher.getByRole("tab");
  await expect(chips).toHaveCount(2);
  await expect(switcher).toContainText(/Flagship/);
  await expect(switcher).toContainText(/North/);

  // ── Switch to North; expect zero bookings carrying this customer name ──
  await switcher.getByRole("tab", { name: /North/ }).click();
  await expect(switcher.getByRole("tab", { name: /North/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  // Wait briefly for the post-switch refetch (admin page has a 12s poll
  // anyway, but the click triggers an immediate dependency-array re-run).
  await page.waitForTimeout(2000);
  // No prior booking has this unique name on the North store.
  await expect(page.locator(".pd-tr", { hasText: northCustomer })).toHaveCount(0);

  // ── Anonymous customer books at /s/playdesk-north/book ──
  const customerPage = await context.newPage();
  // Clean slate: anonymous context. The booking flow doesn't need auth.
  await customerPage.goto(`/s/${NORTH_SLUG}/book`);
  await expect(customerPage.locator("button.pd-rcard").first()).toBeVisible();

  // Pick the first resource + shortest duration.
  await customerPage.locator("button.pd-rcard").first().click();
  await customerPage.locator("button.pd-seg-item").first().click();

  const slot = await pickFirstFreeSlot(customerPage);
  expect(
    slot,
    "no free slot found at the North store — availability is broken",
  ).not.toBe("");

  await customerPage.locator("input.pd-input").first().fill(northCustomer);
  await customerPage.locator("input.pd-input").nth(1).fill("+1 416 555 0199");
  await customerPage.getByRole("button", { name: /Confirm booking/ }).click();
  await expect(
    customerPage.getByRole("heading", { name: /See you at PlayDesk/ }),
  ).toBeVisible();
  await customerPage.close();

  // ── Admin (still on North): refresh, see the new booking ──
  await page.reload();
  // Re-apply North after reload: cookie persists the choice, but allow
  // the StoreContext to settle before asserting.
  await expect(switcher.getByRole("tab", { name: /North/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const northRow = page.locator(".pd-tr", { hasText: northCustomer }).first();
  await expect(northRow).toBeVisible({ timeout: 25_000 });

  // ── Switch to Flagship; the North customer must NOT appear ──
  await switcher.getByRole("tab", { name: /Flagship/ }).click();
  await expect(switcher.getByRole("tab", { name: /Flagship/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // Allow the dependency-array refetch to land.
  await page.waitForTimeout(2000);
  await expect(page.locator(".pd-tr", { hasText: northCustomer })).toHaveCount(0);
});
