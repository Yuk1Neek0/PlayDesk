import { test, expect, type Page } from "@playwright/test";

import { bookFirstFreeSlot, csrfHeaders, signInAsStaff, signInAsStaffAPI } from "./helpers";

// v10b checkin — end-to-end coverage for the per-booking check-in flow.
//
// The flow:
//   1. Customer books a slot through `/`.
//   2. The admin API returns a `check_in_token` on the booking row.
//   3. Customer visits `/c/<token>` and taps "I'm here" — the badge
//      flips to "checked in" and a second tap is idempotent.
//   4. A cancelled booking's token surfaces the cancelled message and
//      hides the button.
//   5. Admin manual check-in on a fresh confirmed booking flips the
//      badge from the table view.
//
// Token discovery: we hit `/api/admin/bookings/?search=<name>` and read
// `check_in_token` off the row. The frontend doesn't render the token
// anywhere customer-visible, which is intentional — only the URL.

const BACKEND_URL = process.env.PLAYDESK_BACKEND ?? "http://localhost:8000";

async function bookOne(page: Page, customer: string, phone: string): Promise<string> {
  // Phase 2 hub: `/` is no longer a redirect, navigate to booking directly.
  await page.goto("/s/playdesk-flagship/book");
  const { slot } = await bookFirstFreeSlot(page, customer, phone);
  return slot;
}

interface BookingRow {
  id: number;
  check_in_token: string | null;
  customer_name: string;
  status: string;
}

async function findBookingByName(page: Page, name: string): Promise<BookingRow> {
  // Pull the admin list directly. v10a StaffOnlyMiddleware gates /api/admin/*
  // so we need a Django session cookie first; signInAsStaffAPI sets it on
  // page.context without the cost of a UI navigation.
  await signInAsStaffAPI(page);
  const resp = await page.request.get(`${BACKEND_URL}/api/admin/bookings/`);
  expect(resp.status()).toBe(200);
  const body = (await resp.json()) as { results: BookingRow[] };
  const row = body.results.find((b) => b.customer_name === name);
  expect(row, `no admin booking row matched customer name ${name}`).toBeDefined();
  return row!;
}

/**
 * Flip a freshly-created booking from its default ``pending`` status to
 * ``confirmed`` via the admin PATCH endpoint. Necessary because every
 * downstream check-in surface (customer ``/c/<token>`` button + admin
 * row's "Check in" button) renders only for CONFIRMED bookings, but the
 * public booking-create returns ``pending`` and the no-deposit branch in
 * ``_maybe_open_deposit`` doesn't upgrade it.
 */
async function confirmBooking(page: Page, bookingId: number): Promise<void> {
  const resp = await page.request.patch(
    `${BACKEND_URL}/api/bookings/${bookingId}/`,
    {
      data: { status: "confirmed" },
      headers: await csrfHeaders(page.context()),
    },
  );
  expect(resp.status(), `confirm patch failed: ${await resp.text()}`).toBeLessThan(300);
}

test("customer check-in happy path: book, tap /c/<token>, see welcome, admin badge flips", async ({
  page,
}) => {
  const customer = `Checkin Happy ${Date.now()}`;
  await bookOne(page, customer, "+1 416 555 0701");

  const row = await findBookingByName(page, customer);
  expect(row.check_in_token).toBeTruthy();
  expect(row.check_in_token!.length).toBe(8);

  // Flip pending → confirmed so the customer-facing check-in button renders.
  await confirmBooking(page, row.id);

  await page.goto(`/c/${row.check_in_token}`);
  await expect(page.getByTestId("checkin-card")).toBeVisible();
  await expect(page.getByTestId("checkin-button")).toBeVisible();
  await page.getByTestId("checkin-button").click();
  await expect(page.getByTestId("checkin-message")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("checkin-message")).toContainText(/Already checked in/);

  // Verify the admin badge — sign in, find the row, look for the green
  // checked-in dot in its Check-in cell. v10a replaced the one-click /login
  // demo button with real /staff/login form auth (see helpers.ts).
  await signInAsStaff(page);
  const adminRow = page.locator(".pd-tr", { hasText: customer }).first();
  await expect(adminRow).toBeVisible({ timeout: 25_000 });
  await expect(adminRow.getByTestId("checkin-badge")).toBeVisible();
});

test("re-tap on /c/<token> after check-in is idempotent: same payload, no error", async ({
  page,
}) => {
  const customer = `Checkin Idempotent ${Date.now()}`;
  await bookOne(page, customer, "+1 416 555 0702");
  const row = await findBookingByName(page, customer);
  await confirmBooking(page, row.id);

  // First tap.
  await page.goto(`/c/${row.check_in_token}`);
  await page.getByTestId("checkin-button").click();
  await expect(page.getByTestId("checkin-message")).toBeVisible({ timeout: 15_000 });

  // Second visit — no button, just the message.
  await page.goto(`/c/${row.check_in_token}`);
  await expect(page.getByTestId("checkin-message")).toBeVisible();
  await expect(page.getByTestId("checkin-message")).toContainText(/Already checked in/);
  await expect(page.getByTestId("checkin-button")).toHaveCount(0);
});

test("cancelled booking on /c/<token> shows the cancelled message, no button", async ({
  page,
}) => {
  const customer = `Checkin Cancelled ${Date.now()}`;
  await bookOne(page, customer, "+1 416 555 0703");
  const row = await findBookingByName(page, customer);

  // Cancel via the admin PATCH endpoint. findBookingByName above logged
  // page.request in as staff (so the StoreOnlyMiddleware lets us through);
  // DRF SessionAuth then enforces CSRF, mirrored from the cookie.
  const cancelResp = await page.request.patch(
    `${BACKEND_URL}/api/bookings/${row.id}/`,
    {
      data: { status: "cancelled" },
      headers: await csrfHeaders(page.context()),
    },
  );
  expect(cancelResp.status()).toBeLessThan(300);

  await page.goto(`/c/${row.check_in_token}`);
  await expect(page.getByTestId("checkin-message")).toContainText(/cancelled/i);
  await expect(page.getByTestId("checkin-button")).toHaveCount(0);
});

test("admin manual check-in for a walk-in flips the badge", async ({ page }) => {
  const customer = `Checkin Walkin ${Date.now()}`;
  await bookOne(page, customer, "+1 416 555 0704");
  const row = await findBookingByName(page, customer);

  // bookOne lands the row at status="pending" (per BookingStatus default
  // + v9 no-deposit path). The manual-checkin button is gated on
  // status==="confirmed", so flip it here before driving the UI.
  await confirmBooking(page, row.id);

  // Sign in to admin via the real /staff/login form (v10a).
  await signInAsStaff(page);

  const adminRow = page.locator(".pd-tr", { hasText: customer }).first();
  await expect(adminRow).toBeVisible({ timeout: 25_000 });

  // The "Check in" button only renders for confirmed bookings.
  await adminRow.getByRole("button", { name: /Check in/ }).click();

  // After the POST settles, the Undo button replaces the manual one.
  await expect(adminRow.getByRole("button", { name: /Undo/ })).toBeVisible({
    timeout: 15_000,
  });
});
