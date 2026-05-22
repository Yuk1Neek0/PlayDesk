import { test, expect } from "@playwright/test";

// J3 — the AI front desk. The "renders" test needs no LLM; the live agent
// test is gated on PLAYDESK_LLM (set when an LLM key is configured) so the
// suite stays green for environments without one.

test("chat page renders the front desk and composer", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "PlayDesk Front Desk" })).toBeVisible();
  await expect(page.locator("textarea.pd-chat-input")).toBeVisible();
  await expect(page.locator("button.pd-suggest-chip").first()).toBeVisible();
});

test("the agent answers a message over the live SSE stream", async ({ page }) => {
  test.skip(!process.env.PLAYDESK_LLM, "needs an LLM key — set PLAYDESK_LLM=1 to run");

  await page.goto("/chat");
  const aiBubbles = page.locator(".pd-bubble--ai");
  const before = await aiBubbles.count();

  await page.locator("textarea.pd-chat-input").fill("What board games do you have?");
  await page.getByRole("button", { name: "Send" }).click();

  // The user's message appears immediately.
  await expect(page.locator(".pd-bubble--user", { hasText: /board games/i })).toBeVisible();

  // A new assistant reply streams in (real LLM call — allow generous time).
  await expect
    .poll(() => aiBubbles.count(), { timeout: 75_000 })
    .toBeGreaterThan(before);
  await expect(aiBubbles.last()).not.toBeEmpty();
});
