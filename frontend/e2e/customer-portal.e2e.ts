import { test, expect, type Page } from "@playwright/test";

// v7 customer-portal — end-to-end happy path.
//
// Drives:
//   login (phone → OTP) → dashboard → cancel a booking → redeem → logout
//
// OTP capture: the backend's `/api/customer-auth/request-code/` endpoint
// echoes the generated code in the response when `?test_mode=1` is set
// AND `DEBUG=True`. docker-compose defaults to DEBUG=true, so the test
// rig can pull the code without a real SMS sink. test_mode also bypasses
// the per-phone rate-limit so the test can drive the UI's Send Code
// button and then re-fetch the latest code without a 60-second wait.
// Production cannot leak the code because DEBUG=False there.
//
// Seeded data (see `core.management.commands.seed_data._seed_customer_portal_fixture`):
//   - Customer "+15551234567" at PlayDesk Flagship
//   - 2 upcoming bookings (48h + 96h out — outside the 24h cancel window)
//   - 1 reward "E2E reward" costing 5 pts
//   - 100-point balance, enough to redeem

const FLAGSHIP_SLUG = "playdesk-flagship";
const E2E_PHONE = "+15551234567";

interface RequestCodeResponse {
  request_id: number;
  code?: string;
}

async function fetchOTP(page: Page): Promise<string> {
  const resp = await page.request.post(`/api/customer-auth/request-code/?test_mode=1`, {
    data: { phone: E2E_PHONE, store_slug: FLAGSHIP_SLUG },
    headers: { "Content-Type": "application/json" },
  });
  expect(resp.ok()).toBeTruthy();
  const body = (await resp.json()) as RequestCodeResponse;
  expect(body.code, "test_mode must surface the OTP code — is DEBUG=True?").toBeTruthy();
  return body.code!;
}

test("customer-portal: login → dashboard → cancel → redeem → logout", async ({
  page,
  context,
}) => {
  // Clear any stale customer cookies from previous runs.
  await context.clearCookies();

  // 1. Land on the portal, see the login form.
  await page.goto(`/s/${FLAGSHIP_SLUG}/account`);
  await expect(page.getByRole("heading", { name: /Sign in with your phone/ })).toBeVisible();

  // 2. Type phone and click Send Code — UI advances to the code step.
  await page.locator("input[type=tel]").fill(E2E_PHONE);
  await page.getByRole("button", { name: /Send code/ }).click();
  await expect(page.getByText(/Code sent to/)).toBeVisible({ timeout: 10_000 });

  // 3. Now hit the test-mode endpoint to invalidate the UI-created OTP
  //    and create a new one whose code we know. test_mode bypasses the
  //    per-minute rate limit so this is immediate.
  const code = await fetchOTP(page);

  // 4. Type the captured code, click Verify — land on dashboard.
  await page.locator("input[autocomplete='one-time-code']").fill(code);
  await page.getByRole("button", { name: /Verify code/ }).click();
  await expect(page.getByRole("heading", { name: /Hello/ })).toBeVisible({ timeout: 15_000 });

  // Tabs render.
  await expect(page.getByRole("tab", { name: /Upcoming/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Loyalty/ })).toBeVisible();

  // 5. Cancel one of the seeded upcoming bookings. They're at 48h and
  //    96h out — both outside the 24h lead window. Use the last row to
  //    keep distance from the lead boundary.
  const rows = page.locator(".pd-row");
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });
  const beforeCount = await rows.count();
  expect(beforeCount).toBeGreaterThan(0);
  await rows.last().getByRole("button", { name: /Cancel/ }).click();
  await page.getByRole("button", { name: /Yes, cancel/ }).click();
  // Row count drops by one after cancel.
  await expect.poll(async () => await rows.count(), { timeout: 10_000 }).toBeLessThan(
    beforeCount,
  );

  // 6. Loyalty tab — redeem the affordable reward.
  await page.getByRole("tab", { name: /Loyalty/ }).click();
  await expect(page.getByText(/Balance/)).toBeVisible();
  const balanceBefore = (await page.locator(".pd-summary-val.pd-mono").first().textContent()) ?? "";
  // Browser-dialog auto-accept for the "Not enough points" path is
  // unnecessary here — the seeded balance covers the reward.
  page.on("dialog", (d) => d.accept());
  const redeemBtn = page.getByRole("button", { name: /Redeem/ }).first();
  await expect(redeemBtn).toBeVisible();
  await redeemBtn.click();
  await expect
    .poll(
      async () => (await page.locator(".pd-summary-val.pd-mono").first().textContent()) ?? "",
      { timeout: 10_000 },
    )
    .not.toBe(balanceBefore);

  // 7. Profile → Logout → bounce to /s/[slug]/book.
  await page.getByRole("tab", { name: /Profile/ }).click();
  await page.getByRole("button", { name: /Log out/ }).click();
  await expect(page).toHaveURL(new RegExp(`/s/${FLAGSHIP_SLUG}/book$`), { timeout: 10_000 });

  // 8. Revisit /account — login form shows again (session cleared).
  await page.goto(`/s/${FLAGSHIP_SLUG}/account`);
  await expect(page.getByRole("heading", { name: /Sign in with your phone/ })).toBeVisible();
});
