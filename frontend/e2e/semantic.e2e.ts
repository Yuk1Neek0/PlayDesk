import { test, expect, type Page } from "@playwright/test";

// Semantic E2E — the layer that asserts the UI reflects *reality*, not just
// that the contract is honoured.
//
// 1. The booking calendar's "today" label always names today in
//    America/Toronto (not the viewer's clock, not a frozen prototype date).
// 2. A booking made via `/` is visible to the agent on `/chat` immediately —
//    the agent must report the just-booked resource as taken when asked.

const STORE_TZ = "America/Toronto";

interface TorontoToday {
  isoDate: string;        // "YYYY-MM-DD"
  weekdayShort: string;   // "Mon"
  dayNum: string;         // "22"
  monthShort: string;     // "May"
}

function torontoToday(): TorontoToday {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: STORE_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const year = parts.find((p) => p.type === "year")!.value;
  const month = parts.find((p) => p.type === "month")!.value;
  const day = parts.find((p) => p.type === "day")!.value;
  // en-GB weekday/month abbreviations are what the booking page renders.
  const weekdayShort = new Intl.DateTimeFormat("en-GB", {
    timeZone: STORE_TZ,
    weekday: "short",
  }).format(now);
  const monthShort = new Intl.DateTimeFormat("en-GB", {
    timeZone: STORE_TZ,
    month: "short",
  }).format(now);
  return {
    isoDate: `${year}-${month}-${day}`,
    weekdayShort,
    dayNum: String(parseInt(day, 10)),
    monthShort,
  };
}

test("date strip starts on today (store timezone), regardless of viewer TZ", async ({ page }) => {
  // Reproduces the frozen-clock regression: the prototype hard-coded
  // 2026-05-21 as "today", so the strip kept labelling May 21 as today and
  // offered it as a bookable date forever. The viewer is in Asia/Tokyo
  // per playwright.config.ts — the strip must still anchor on Toronto.

  await page.goto("/");
  // Pick any resource so step 2 (the strip) becomes interactive.
  await page.locator("button.pd-rcard").first().click();
  const first = page.locator("button.pd-date-cell").first();
  await expect(first).toBeVisible();

  const today = torontoToday();

  // The first cell carries the "· today" badge in its month line.
  await expect(first.locator(".pd-date-mon")).toContainText("today");

  // The numeric day matches Toronto today.
  await expect(first.locator(".pd-date-num")).toHaveText(today.dayNum);

  // Weekday + month abbreviations match Toronto today.
  await expect(first.locator(".pd-date-day")).toHaveText(today.weekdayShort);
  await expect(first.locator(".pd-date-mon")).toContainText(today.monthShort);
});

/** Click date cells until the slot grid offers a bookable hour; return the picked label. */
async function pickFirstFreeSlot(page: Page): Promise<{ slot: string; resourceName: string }> {
  const resourceName = (await page
    .locator("button.pd-rcard.is-selected .pd-rcard-name")
    .textContent())?.trim() ?? "";
  const dates = page.locator("button.pd-date-cell");
  const count = await dates.count();
  for (let i = 0; i < count; i++) {
    await dates.nth(i).click();
    await page.waitForTimeout(2000);
    const free = page.locator(".pd-slots-grid button.pd-slot:not([disabled])").first();
    if ((await free.count()) > 0) {
      const slot = (await free.locator(".pd-slot-time").textContent())?.trim() ?? "";
      await free.click();
      return { slot, resourceName };
    }
  }
  return { slot: "", resourceName };
}

test("a manual booking is visible to the AI front desk on the next turn", async ({ page }) => {
  test.skip(!process.env.PLAYDESK_LLM, "needs an LLM key — set PLAYDESK_LLM=1 to run");

  const customer = `Playwright AI ${Date.now()}`;

  // ---- Book via / ----
  await page.goto("/");
  await expect(page.locator("button.pd-rcard").first()).toBeVisible();
  await page.locator("button.pd-rcard").first().click();
  // Shortest duration so finding a slot is easy.
  await page.locator("button.pd-seg-item").first().click();
  const { slot, resourceName } = await pickFirstFreeSlot(page);
  expect(slot, "no free slot in the picker — availability is broken").not.toBe("");
  expect(resourceName, "could not read the selected resource name").not.toBe("");

  // The cell that has the .is-selected class corresponds to the chosen date.
  const selectedDateNum = await page
    .locator("button.pd-date-cell.is-selected .pd-date-num")
    .textContent();
  expect(selectedDateNum).not.toBeNull();

  await page.locator("input.pd-input").first().fill(customer);
  await page.locator("input.pd-input").nth(1).fill("+1 416 555 0177");
  await page.getByRole("button", { name: /Confirm booking/ }).click();
  await expect(page.getByRole("heading", { name: /See you at PlayDesk/ })).toBeVisible({
    timeout: 25_000,
  });

  // ---- Ask the AI ----
  await page.goto("/chat");
  await expect(page.locator("textarea.pd-chat-input")).toBeVisible();

  const aiBubbles = page.locator(".pd-bubble--ai");
  const before = await aiBubbles.count();

  // Ask in store-local terms. Day-of-month is what's shown in the strip;
  // pairing it with the hour gives the agent enough to resolve a concrete
  // date+time.
  const hour = parseInt(slot, 10);
  const question =
    `Is the ${resourceName} available on day ${selectedDateNum} of this month at ${hour}:00?`;

  await page.locator("textarea.pd-chat-input").fill(question);
  await page.getByRole("button", { name: "Send" }).click();
  await expect
    .poll(() => aiBubbles.count(), { timeout: 90_000 })
    .toBeGreaterThan(before);

  const reply = (await aiBubbles.last().textContent()) ?? "";
  expect(reply.length, "AI reply was empty").toBeGreaterThan(0);

  // The reply should mention a "taken" sense — the resource the user just
  // booked must not be reported as free at the same hour.
  const takenWords = /not available|unavailable|already booked|taken|booked|reserved|sorry|afraid|conflict/i;
  expect(reply, `AI reply did not indicate the slot is taken: ${reply}`).toMatch(takenWords);
});
