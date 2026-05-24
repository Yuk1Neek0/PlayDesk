// One-shot screenshot script for the Phase 2 design refresh.
// Boots no browser of its own — relies on a Next.js server already
// running at the URL passed in BASE_URL (default http://localhost:3050)
// and a backend at http://127.0.0.1:8000. Saves PNGs under
// frontend/verify_v11d_shots/.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SHOT_DIR = resolve(__dirname, "..", "verify_v11d_shots");
mkdirSync(SHOT_DIR, { recursive: true });

const BASE = process.env.BASE_URL ?? "http://localhost:3050";

// Find a token for /c/<token> by hitting the backend admin list directly.
async function findCheckinKey() {
  try {
    const resp = await fetch("http://127.0.0.1:8000/api/c-in/active-key/");
    if (!resp.ok) return null;
    const body = await resp.json();
    return body.key ?? null;
  } catch {
    return null;
  }
}

const shots = [
  { name: "01_hub_desktop", url: "/", viewport: { width: 1440, height: 900 } },
  { name: "02_hub_mobile", url: "/", viewport: { width: 375, height: 667 } },
  {
    name: "03_book_desktop",
    url: "/s/playdesk-flagship/book",
    viewport: { width: 1440, height: 900 },
  },
  {
    name: "04_book_mobile",
    url: "/s/playdesk-flagship/book",
    viewport: { width: 375, height: 667 },
  },
  { name: "05_staff_login_desktop", url: "/staff/login", viewport: { width: 1440, height: 900 } },
  { name: "06_staff_login_mobile", url: "/staff/login", viewport: { width: 375, height: 667 } },
];

const checkinKey = await findCheckinKey();
if (checkinKey) {
  shots.push({
    name: "07_checkin_mobile",
    url: `/c-in/?k=${encodeURIComponent(checkinKey)}`,
    viewport: { width: 375, height: 667 },
  });
}

const browser = await chromium.launch();
for (const s of shots) {
  const ctx = await browser.newContext({ viewport: s.viewport });
  const page = await ctx.newPage();
  const target = `${BASE}${s.url}`;
  try {
    await page.goto(target, { waitUntil: "networkidle", timeout: 20_000 });
  } catch {
    await page.goto(target, { waitUntil: "domcontentloaded", timeout: 20_000 });
  }
  // Brief settle so animations land.
  await page.waitForTimeout(800);
  const out = resolve(SHOT_DIR, `${s.name}.png`);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`saved ${out}`);
  await ctx.close();
}
await browser.close();
