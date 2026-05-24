# PlayDesk frontend — design audit (Phase 1)

Scope: customer-facing surfaces (`/`, `/s/[slug]/book`, `/s/[slug]/account`,
`/qr/[slug]`, `/c/[token]`, `/c-in/`, `/chat`, `/staff/login`). `/admin/*`
visual polish deferred — structural notes only.

Stack reminder: Next.js 14 App Router, Tailwind preflight only, custom
`pd-*` system in `src/app/playdesk.css` (~890 LOC), three Google fonts wired
via `next/font` (Inter / Space Grotesk / JetBrains Mono).

---

## 1. Concrete weaknesses

### 1a. Half the customer surface ships unstyled — missing CSS classes
The check-in flows, the customer portal list/row/modal primitives, and the
QR landing's account-foot variant all reference classes that **do not exist
in `playdesk.css` or anywhere else**:

- `pd-checkin-page`, `pd-checkin-card`, `pd-checkin-head`, `pd-checkin-logo`,
  `pd-checkin-store`, `pd-checkin-body`, `pd-checkin-greeting`,
  `pd-checkin-context`, `pd-checkin-resource`, `pd-checkin-time`,
  `pd-checkin-btn`, `pd-checkin-status`, `pd-checkin-status--*`,
  `pd-checkin-error`, `pd-checkin-list`, `pd-checkin-list-item` — used in
  `src/app/c/[token]/CheckInClient.tsx:96-145` and
  `src/app/c-in/RotatingCheckinClient.tsx:191-407`
- `pd-row`, `pd-row-main`, `pd-row-title`, `pd-row-sub`, `pd-row-actions`,
  `pd-list`, `pd-modal`, `pd-modal-card`, `pd-status-*`,
  `pd-page--booking`, `pd-page-head-row` — used across
  `src/app/s/[slug]/account/AccountDashboard.tsx:304-696` and
  `src/app/s/[slug]/book/BookingPage.tsx:434,436`
- `pd-qr-foot--with-account` — `src/app/qr/[slug]/QRLanding.tsx:144`

These render with **Tailwind preflight defaults only** — naked black text on
the body's dark gradient, unaligned modal overlays, no spacing between
booking rows. This is the single biggest visible problem on the
customer-facing surface and it affects the most-trafficked mobile flows
(QR check-in and the account portal).

### 1b. Staff login is a different product
`src/app/staff/login/LoginForm.tsx:57-127` is pure Tailwind utility
classes — `bg-white`, `text-gray-900`, `border-gray-300`, `bg-gray-800`.
Light theme, gray buttons, no `pd-*` tokens. A staff member who clicks
"Sign in" in the dark `pd-nav` is hard-cut to what looks like a different
app. The customer portal login at `src/app/s/[slug]/account/LoginForm.tsx`
does use the `pd-*` system correctly — so the inconsistency is purely
within the staff path.

### 1c. Body font is too small for mobile, hero is fixed at 32px
`--fs-body: 14.5px` (`playdesk.css:68`) is on the small side desktop and
genuinely cramped on a phone, where customer flows actually happen. The
booking page hero `pd-page-title` uses `clamp(38px, 5.2vw, 60px)`
(`playdesk.css:65`) — but the `@media (max-width: 720px)` override at
`playdesk.css:892` slams it back to a flat `32px`. Phones lose the entire
display-type moment; you end up with a 32 px heading sitting on 14.5 px
body — a weak ramp. The "Pick your station, set your night." hero
(`BookingPage.tsx:459-463`) is the single most expressive piece of type on
the site and it's invisible on the device where most customers see it.

### 1d. Cyan accent + glow appears on everything; nothing reads as primary
`var(--accent-glow)` is attached to: the brand mark (`playdesk.css:133`),
every primary button (`:171`), the active nav underline (`:147`), every
selected resource card (`:278`), every selected date cell (`:319`), every
selected time slot (`:350`), the confirmation stamp (`:434, 738`), the
booking card border (`:530`), the new-row marker in admin tables (`:704`),
the send icon button (`:571`), and the live pulse strip. The cyan also
carries the per-store accent override. The net effect on the booking page
once a customer picks a resource + date + slot is **four simultaneous
glowing cyan elements** competing for the eye, with the actual "Confirm
booking" CTA fighting all of them. The accent has lost its job.

### 1e. The booking page hero is over-promised; the cards under it are anonymous
The header at `BookingPage.tsx:435-467` does heroic work — display type,
eyebrow, two-line title, sub-copy, brand logo. Then we drop into
`.pd-rcard` (resource cards) where the 16:9 art slot is just `pd-art-stripes`
— a repeating 1 px diagonal hairline on a flat surface, with a tinted icon
floating in it (`playdesk.css:293-305`). For a gaming-lounge product whose
identity is "what does the room look like", the cards are the part that
should sell the vibe; they're the most generic part of the page. The
`pd-empty` and `pd-error` states (`playdesk.css:377, 415`) are similarly
plain — dashed border, dim text, no character. Compare to the typography
investment in `pd-confirmed-title` (`playdesk.css:444`, "See you at
PlayDesk.") which lands beautifully.

---

## 2. Three directional options

### Option A — "Tighten the system you already have"
**Vibe.** Keep the dark gaming-lounge aesthetic, the cyan accent, and the
three-font stack. Fix what's broken: implement the missing `pd-*` classes,
port staff login into the system, raise body type to 15–16 px, ratchet down
glow noise so the accent only fires on the one true primary at a time, and
give the resource cards real character (subtle per-type color band, larger
art).

**Touches most.** Check-in pages and customer portal (where the missing
CSS lives), staff login, booking page card grid, and the body-font /
mobile-hero scale.

**Tradeoff.** Lowest risk, fastest, the highest user-visible improvement
per byte changed. Will not feel like a "redesign" — more like the polish
pass that the existing system was always implying.

### Option B — "Warm editorial — slow it down"
**Vibe.** Lean into the gaming-lounge-as-bar metaphor instead of the
gaming-lounge-as-arcade one. Larger margins, a true display serif
(e.g. promote one of the existing system stacks via CSS variable — no new
dep needed) on `pd-page-title` / `pd-confirmed-title` only, body stays
Inter. Surface stays near-black but warms 4–6 points toward bistro brown.
The accent stops being a uniform cyan — it becomes the **per-store brand
color**, used sparingly (one CTA per screen). Glow retired.

**Touches most.** Booking + account hero typography, QR landing, the
confirmation surface, the resource cards (which become photo-forward
postcards). Admin can opt in or stay literal.

**Tradeoff.** Stronger identity; potential mismatch for stores whose vibe
is loud / esports. Higher work: needs a font choice + a re-pass on the
resource-art slot. The "warm editorial" frame depends on photography we
don't currently have — without it, the surface risks reading as bland.

### Option C — "Mobile-native — phones are the product"
**Vibe.** Rebuild the booking flow and check-in flow as bottom-sheet-shaped
stacks: sticky bottom CTA, full-bleed step cards, native-feeling segmented
controls, tactile haptics-style press states. Desktop becomes a centered
column with a phone-mock chrome around it. Type uses Inter throughout for
maximum legibility; Space Grotesk reserved for the brand mark + price
moments only. Accent stays cyan but moves from "glow" to "fill" (denser,
no shadow).

**Touches most.** Every customer flow — booking, account, QR landing,
check-in, chat composer.

**Tradeoff.** Highest user value on mobile (where most scans land);
desktop becomes deliberately secondary. Highest scope and biggest visual
break from the existing prototype. Locks the product into a phone-first
position which is honest but commits the brand.

---

## 3. Recommendation — Option A, with one Option B borrow

**Take Option A as Phase 2's anchor.** The missing-CSS problem (§1a) is
unambiguously a bug, not a design call, and shipping the correct styles
for the check-in pages and customer portal is the single most disruptive
"refresh" you can deliver — a meaningful share of the customer surface
literally has no design today. Staff login (§1b) is the same shape of
fix. Doing these two well costs ~150 lines of CSS and zero risk.

On top of that, take one move from Option B: **promote the hero type and
demote the glow**. Specifically:

- Raise `--fs-body` to 15.5 px and let `--fs-display` clamp continue to
  scale on phones (delete the `pd-page-title { font-size: 32px }` mobile
  override at `playdesk.css:892`).
- Drop `var(--accent-glow)` from non-primary elements (date cells, slot
  cells, brand mark, conv rows, table rows) — keep it only on the actual
  primary CTA and the confirmation stamp. The cyan stays as a fill /
  border color; it just stops shouting from five places at once.

That gets us the perceived "better typography, better layout, more
restrained" lift the user is asking for, without forcing a brand pivot or
a photography dependency we can't yet meet. Reserve Options B and C as
follow-up epics if the user wants to keep going.

---

## 4. The `/` homepage call — recommend: become a hub

**Recommendation: make `/` a real landing.** Today `src/app/page.tsx` is a
server-side 302 to `/s/<default-slug>/book`. The single biggest argument
for keeping the redirect is that printed QR cards / bookmarks pointing at
`/` keep working — but that's already handled the moment `/` renders a
page with a primary "Book now" tile that links to `/s/<default>/book`. The
redirect costs us:

- **No discoverability for staff** — a front-desk PC bookmarked at the
  root domain dumps the staff member into a customer booking screen.
  They have to know to type `/staff/login` or hunt the "Sign in" chip in
  the nav.
- **No top-of-funnel surface** — there is literally nowhere on the
  product today to put "what is PlayDesk", store hours, the AI chat
  affordance ahead of the booking flow, or a "scan QR at the desk"
  prompt for in-person walk-ins.
- **Per-store branding is invisible** at the root — the redirect target
  inherits the alphabetically-first / DB-flagged default; the visitor
  never sees the brand surface for any other location.

A hub layout with four explicit entries — **Book now**, **My account**,
**Talk to front desk** (AI chat), **Staff sign in** — costs one new
component, keeps backward compatibility (Book now links to
`/s/<default>/book`, which is exactly the current redirect target), and
turns `/` into a place the brand can actually live. Mobile-first: the
four entries become a vertical stack with the booking CTA as the prominent
one; desktop gets a 2×2 grid.

The trade is one round-trip vs zero for first-time QR scanners — but
first-time scanners hit `/s/<slug>/book` directly via the printed QR, not
`/`. The redirect was a v6-multi-location migration convenience, not an
intentional information architecture choice. Time to retire it.

---

## Phase 2 deliverable (preview only, not built here)

If the user picks Recommendation §3 + Hub §4, Phase 2 is roughly:

1. **One commit, missing-CSS fix.** Define the `pd-checkin-*`, `pd-row`,
   `pd-list`, `pd-modal`, `pd-status-*`, `pd-page--booking`,
   `pd-page-head-row`, `pd-qr-foot--with-account` classes in
   `playdesk.css` so the check-in / account / QR-foot surfaces match the
   rest of the system.
2. **One commit, staff login + type/glow pass.** Rewrite
   `staff/login/LoginForm.tsx` against `pd-*`. Raise body to 15.5 px,
   drop the 32 px mobile hero clamp, prune `var(--accent-glow)` from
   non-primary elements.
3. **One commit, `/` hub.** Replace `app/page.tsx` redirect with a real
   hub component; keep the `/api/public/default-store/` lookup so "Book
   now" still points at the default store. Verify nothing in
   `e2e/multi-location.e2e.ts` or the customer-portal e2e expects a 302.

Each commit can ship independently; each is a few-hundred-line change at
most. Tests: `npm run lint && npm run typecheck && npm test && npm run
build` plus a Playwright smoke on `/`, `/s/[slug]/book`, `/c-in/`,
`/staff/login`.
