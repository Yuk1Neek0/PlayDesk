import { test, expect, type Page } from "@playwright/test";

// J5 — v4 cross-slice integration. Catches the class of bug where each
// slice's own tests pass but the admin pages 5xx / show "Couldn't load …"
// banners under the real demo Staff session (see PR #129's hotfix).
//
// Two tests:
//   1. Smoke — every v4 admin page renders without an error banner.
//      Fast (~10s), no seed needed: empty-state lists are the assertion.
//   2. Integrated — a real booking through the UI creates a Customer,
//      fires booking signals, enqueues an outbound message, and the
//      customer-detail page renders BOTH the Membership card and the
//      Outbound messages section with that real data.

async function signInAsStaff(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: /Staff/ }).click();
  await expect(page).toHaveURL(/\/admin/);
}

test("v4 admin pages render under Staff login (no 'Couldn't load' banners)", async ({ page }) => {
  await signInAsStaff(page);

  // The "Couldn't load …" banner is the symptom of an API auth/data fetch
  // failure (e.g. PR #129's 403). It exists in the pd-error style. Asserting
  // its absence per page is the cheap regression net for that class of bug.
  const errorBanner = page.locator(".pd-error");

  // /admin/rewards — memberships CRUD (was 403 before PR #129)
  await page.goto("/admin/rewards");
  await expect(errorBanner).toHaveCount(0);

  // /admin/tiers — memberships CRUD (was 403 before PR #129)
  await page.goto("/admin/tiers");
  await expect(errorBanner).toHaveCount(0);

  // /admin/segments — campaigns CRUD
  await page.goto("/admin/segments");
  await expect(page.getByRole("heading", { name: /Customer segments/i })).toBeVisible();
  await expect(errorBanner).toHaveCount(0);

  // /admin/campaigns — campaigns list
  await page.goto("/admin/campaigns");
  await expect(page.getByRole("heading", { name: /Marketing sends/i })).toBeVisible();
  await expect(errorBanner).toHaveCount(0);

  // /admin/campaigns/new — 4-step campaign builder
  await page.goto("/admin/campaigns/new");
  await expect(page.getByRole("heading", { name: /Compose & send/i })).toBeVisible();
  await expect(errorBanner).toHaveCount(0);
});

/** Walk the booking picker until a free slot is found; click it. */
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

test("customer detail page shows BOTH membership + outbound sections with real data", async ({
  page,
}) => {
  // Make a fresh customer + booking through the live UI. This exercises the
  // real booking-create path, which fires the v4 outbound signal that
  // enqueues a booking_confirmation OutboundMessage.
  //
  // Unique phone per run: the retention slice dedups Customers by normalized
  // phone, so a shared phone would merge into a long-lived test customer and
  // hide bugs. A random 4-digit suffix gives us a fresh Customer per run.
  const phoneSuffix = String(Math.floor(1000 + Math.random() * 9000));
  const customerName = `Playwright v4 ${Date.now()}`;
  const customerPhone = `+1 416 555 ${phoneSuffix}`;

  await page.goto("/");
  await page.locator("button.pd-rcard").first().click();
  await page.locator("button.pd-seg-item").first().click();
  const slot = await pickFirstFreeSlot(page);
  expect(slot, "no free slot — availability is broken").not.toBe("");
  await page.locator("input.pd-input").first().fill(customerName);
  await page.locator("input.pd-input").nth(1).fill(customerPhone);
  await page.getByRole("button", { name: /Confirm booking/ }).click();
  await expect(page.getByRole("heading", { name: /See you at PlayDesk/ })).toBeVisible();

  // Sign in as staff and use the search box (more reliable than scanning
  // rows in a paginated list that may contain hundreds of test customers).
  await signInAsStaff(page);
  await page.goto("/admin/customers");
  await page.getByPlaceholder(/Search by name or phone/i).fill(customerPhone);
  const row = page.locator(".pd-tr", { hasText: customerName }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
  await row.click();
  await expect(page).toHaveURL(/\/admin\/customers\/\d+/);

  // Membership card — from v4 memberships slice. The composite endpoint
  // returns balance/tier/transactions/rewards in one payload; balance is the
  // headline number on a fresh customer (0). Targeting the h2 specifically
  // because the loading-state empty div also contains the word "Membership".
  await expect(page.getByRole("heading", { name: "Membership", exact: true })).toBeVisible({
    timeout: 10_000,
  });

  // Outbound messages section — from v4 outbound slice. The booking signal
  // enqueued a booking_confirmation row at the moment we confirmed above.
  await expect(page.getByRole("heading", { name: /Outbound messages/i })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText(/booking_confirmation/)).toBeVisible({ timeout: 10_000 });

  // No "Couldn't load" anywhere — proves the data fetches all returned 2xx.
  await expect(page.locator(".pd-error")).toHaveCount(0);
});
