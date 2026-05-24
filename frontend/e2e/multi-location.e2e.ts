import { test, expect } from "@playwright/test";

import { bookFirstFreeSlot, signInAsStaff } from "./helpers";

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

// Multi-step journey: admin sign-in + store switch + customer booking
// (with retry-on-conflict) + admin refresh + cross-store assert. Bumps
// the default 90s timeout — the booking flow alone can walk a half-dozen
// dates when accumulated state has filled the early ones.
test.setTimeout(180_000);

test("cross-store isolation: book at North, only visible while admin is on North", async ({
  page,
  context,
}) => {
  const northCustomer = `MultiLocNorth ${Date.now()}`;

  // ── Admin: sign in and verify the StoreSwitcher exposes both stores ──
  await signInAsStaff(page);

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
  // Use a *separate* browser context so the admin sessionid + csrftoken
  // cookies don't bleed into the public booking POST. DRF's
  // SessionAuthentication enforces CSRF whenever a session cookie is
  // present, and the public booking endpoint doesn't get a CSRF token
  // from a customer-flow page — so the inherited cookie would 403 the
  // create call. A fresh context starts cookie-free, the way a real
  // anonymous visitor at /s/<slug>/book is.
  const browser = context.browser();
  if (!browser) throw new Error("context lost its browser handle");
  const baseURL = process.env.PLAYDESK_WEB ?? "http://localhost:3000";
  const customerContext = await browser.newContext({ baseURL });
  const customerPage = await customerContext.newPage();
  await customerPage.goto(`/s/${NORTH_SLUG}/book`);
  // Helper handles resource + duration + slot picking, with 409 retries.
  await bookFirstFreeSlot(customerPage, northCustomer, "+1 416 555 0199");
  await customerPage.close();
  await customerContext.close();

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
