import { execSync } from "node:child_process";

import { test, expect } from "@playwright/test";

// J6 — v5 branded-booking: the SSR loader pulls the store's brand from
// /api/public/store-brand/ and either renders the default logo SVG or the
// store's <img>; when an accent is set, the wrapper gets a `--pd-accent`
// inline CSS variable.
//
// The brand is normally admin-set; for this test we mutate the demo store's
// `Store.brand` via the running backend container (`docker compose exec ...`)
// because there is no admin REST endpoint for the field in v5. The mutation
// is reverted in `test.afterEach` so other suites see a clean default.

const ACCENT = "oklch(0.78 0.16 200)";
const LOGO_URL =
  "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png";

function setBrand(brandJson: string): void {
  // The compose stack the suite runs against is already up (see CLAUDE.md
  // and playwright.config.ts). The Django shell -c is one round-trip; the
  // 60s public/store-brand cache is per-Next-process, but Next dev/standalone
  // builds with `cache: "default"` will re-fetch on the next request as long
  // as we tag the brand fetch with a unique cache-buster query — we don't,
  // so we rely on the brand being set BEFORE the page navigation below.
  const py = `from core.models import Store; s=Store.objects.first(); s.brand=${brandJson}; s.save()`;
  execSync(
    `docker compose exec -T backend python manage.py shell -c "${py.replace(/"/g, '\\"')}"`,
    { stdio: ["ignore", "ignore", "inherit"] },
  );
}

test.beforeEach(() => {
  // Start each test from the default (empty) brand state.
  setBrand("{}");
});

test.afterAll(() => {
  setBrand("{}");
});

test("brand={} renders the default-state header (no logo image, no inline accent)", async ({
  page,
}) => {
  // Phase 2 hub: `/` is no longer a redirect; the brand surface lives on
  // the store-scoped booking page.
  await page.goto("/s/playdesk-flagship/book");
  await expect(page.getByRole("heading", { name: /Pick your station/ })).toBeVisible();

  // No branded <img> — the default SVG mark renders instead.
  await expect(page.locator(".pd-brand-logo-img")).toHaveCount(0);
  await expect(page.locator(".pd-brand-logo .pd-brand-mark")).toHaveCount(1);

  // The wrapper carries no inline style override → default `--accent` wins.
  const wrapperStyle = await page.locator(".pd-page--booking").getAttribute("style");
  expect(wrapperStyle ?? "").not.toContain("--pd-accent");
});

test("brand={logo_url, accent} renders the <img> and sets --pd-accent on the wrapper", async ({
  page,
}) => {
  setBrand(`{"logo_url": "${LOGO_URL}", "accent": "${ACCENT}"}`);

  await page.goto("/s/playdesk-flagship/book");
  await expect(page.getByRole("heading", { name: /Pick your station/ })).toBeVisible();

  const img = page.locator(".pd-brand-logo-img");
  await expect(img).toHaveCount(1);
  await expect(img).toHaveAttribute("src", LOGO_URL);

  const wrapperStyle = await page.locator(".pd-page--booking").getAttribute("style");
  expect(wrapperStyle ?? "").toContain("--pd-accent");
  expect(wrapperStyle ?? "").toContain(ACCENT);
});
