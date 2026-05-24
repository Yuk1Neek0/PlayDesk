import type { APIRequestContext, BrowserContext, Page } from "@playwright/test";
import { expect } from "@playwright/test";

// Shared e2e helpers (v10a staff-auth).
//
// The v10a real-login flow replaces the old "click 'Staff'" one-click
// demo button. Every admin-driving e2e test that previously did
//     await page.goto("/login");
//     await page.getByRole("button", { name: /Staff/ }).click();
// now goes through `signInAsStaff(page)` which exercises the real
// `/staff/login/` form with the seeded `playdesk_staff` credentials.

export const STAFF_USERNAME = "playdesk_staff";
export const STAFF_PASSWORD = "playdesk_staff_demo_pw";

/**
 * Sign into the admin app using the seeded staff credentials.
 *
 * Navigates to /staff/login and submits the real Django session
 * login form. Does not assert the post-login URL — callers do that
 * because some tests want to be on `/admin`, others on a deep link.
 */
export async function signInAsStaff(page: Page): Promise<void> {
  await page.goto("/staff/login");
  // /staff/login server-redirects to /admin when the session cookie is
  // already valid (e.g. a prior test in the same context already signed
  // in). Skip the form when the cookie carries — saves a UI round-trip
  // and avoids the rate limiter ticking.
  if (/\/admin/.test(page.url())) return;
  await page.getByLabel("Username").fill(STAFF_USERNAME);
  await page.getByLabel("Password").fill(STAFF_PASSWORD);
  await page.getByRole("button", { name: /Sign in/ }).click();
  // Wait until the form's full-page navigation completes so callers can
  // rely on subsequent goto()/asserts running against the new context.
  await page.waitForURL(/\/admin/, { timeout: 20_000 });
}

/**
 * Authenticate `page.request` (an APIRequestContext sharing the page's
 * cookies) by calling /api/staff/login/ directly. Returns silently when the
 * credentials are accepted; throws otherwise so tests fail loudly. Use this
 * instead of `signInAsStaff` when you only need the cookies on
 * `page.request.*` and don't want the cost of a UI round-trip.
 *
 * Both functions set the same Django session + csrftoken cookies on the
 * shared browser context, so subsequent UI navigation will also be signed in.
 */
export async function signInAsStaffAPI(page: Page): Promise<void> {
  const resp = await page.request.post("/api/staff/login/", {
    data: { username: STAFF_USERNAME, password: STAFF_PASSWORD },
    headers: { "Content-Type": "application/json" },
  });
  if (!resp.ok()) {
    throw new Error(`staff API login failed: ${resp.status()} ${await resp.text()}`);
  }
}

/**
 * Read the Django `csrftoken` cookie off the page's browser context and
 * return it as a header bag suitable for spreading into a `page.request.*`
 * call. The staff-login response always sets this cookie; if it isn't
 * present we still return an empty object so the caller's code stays
 * uniform (Django will surface the missing token as a 403 the test sees).
 */
export async function csrfHeaders(
  context: BrowserContext | APIRequestContext,
): Promise<Record<string, string>> {
  const storage = "storageState" in context ? await context.storageState() : null;
  if (!storage) return {};
  for (const c of storage.cookies) {
    if (c.name === "csrftoken") return { "X-CSRFToken": c.value };
  }
  return {};
}

/**
 * Drive the customer booking page through to the "See you at PlayDesk"
 * confirmation. Picks the first resource + 1h duration, then walks future
 * dates looking for a free hour. On a 409 ("slot just taken") from the
 * booking POST — which happens regularly on long-running dev/CI stacks
 * because cancelled bookings still block the GIST overlap constraint —
 * dismisses the inline error and tries the next free slot.
 *
 * Returns the (date-cell-index, slot-label) that ultimately took.
 */
export async function bookFirstFreeSlot(
  page: Page,
  customer: string,
  phone: string,
): Promise<{ slot: string }> {
  await expect(page.locator("button.pd-rcard").first()).toBeVisible();
  await page.locator("button.pd-rcard").first().click();
  await page.locator("button.pd-seg-item").first().click();

  const dates = page.locator("button.pd-date-cell");
  const dateCount = await dates.count();
  const triedSlotKeys = new Set<string>();
  let formFilled = false;

  // Start at 1 — `today` accumulates leftover test bookings across runs.
  for (let i = 1; i < dateCount; i++) {
    await dates.nth(i).click();
    // Wait for availability to arrive: slot grid renders fresh on date
    // change. The .pd-slot-time inside any slot button is what we read
    // below, so wait for at least one to mount or 1s for an empty day.
    await page
      .locator(".pd-slots-grid .pd-slot")
      .first()
      .waitFor({ state: "attached", timeout: 5_000 })
      .catch(() => {});
    await page.waitForTimeout(500);

    // Try every free slot on this day, in order, until one books or the
    // grid is exhausted.
    while (true) {
      const free = page.locator(
        ".pd-slots-grid button.pd-slot:not([disabled])",
      );
      const slotCount = await free.count();
      let picked: { idx: number; label: string } | null = null;
      for (let j = 0; j < slotCount; j++) {
        const label =
          (await free.nth(j).locator(".pd-slot-time").textContent())?.trim() ?? "";
        const key = `${i}|${label}`;
        if (triedSlotKeys.has(key)) continue;
        triedSlotKeys.add(key);
        picked = { idx: j, label };
        break;
      }
      if (!picked) break; // no fresh slots on this day — go to next date

      await free.nth(picked.idx).click();

      // Form inputs are `disabled={!slot}`; fill them only after the first
      // slot click. The values stick across re-picks (React state).
      if (!formFilled) {
        await page.locator("input.pd-input").first().fill(customer);
        await page.locator("input.pd-input").nth(1).fill(phone);
        formFilled = true;
      }

      await page.getByRole("button", { name: /Confirm booking/ }).click();

      // Race between success heading and the booking-page error states:
      // - "That slot was just taken" — 409 from the GIST constraint;
      //   retry with the next slot.
      // - "Something went wrong" — generic 4xx/5xx; surface verbatim so
      //   we don't burn the whole 14-day strip on a real bug.
      const success = page.getByRole("heading", { name: /See you at PlayDesk/ });
      const taken = page.getByText(/That slot was just taken/);
      const generic = page.getByText(/Something went wrong creating your booking/);
      try {
        await expect(success.or(taken).or(generic)).toBeVisible({ timeout: 15_000 });
      } catch {
        // Neither showed up — fall through and try another slot.
      }
      if (await success.isVisible().catch(() => false)) {
        return { slot: picked.label };
      }
      if (await generic.isVisible().catch(() => false)) {
        throw new Error(
          "bookFirstFreeSlot: booking-create returned a non-409 error " +
            `("Something went wrong creating your booking"). Slot ${picked.label} ` +
            `on day index ${i}; investigate backend logs.`,
        );
      }
      // Conflict: dismiss the error implicitly by picking again. The form
      // stays mounted (state is preserved) so the next click resubmits.
    }
  }
  throw new Error("bookFirstFreeSlot: exhausted 14 days without a free slot");
}
