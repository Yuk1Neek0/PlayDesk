# Claude Design Prompts — Frontend Pages

Paste-ready prompts for designing the PlayDesk frontend in **Claude Design**
(Anthropic Labs). The page UIs for the `frontend` epic — tasks
[#20](https://github.com/Yuk1Neek0/PlayDesk/issues/20),
[#21](https://github.com/Yuk1Neek0/PlayDesk/issues/21),
[#22](https://github.com/Yuk1Neek0/PlayDesk/issues/22) — are built from these
designs. Export the result ("Handoff to Claude Code" / standalone HTML / `.zip`)
into the repo to unblock those tasks.

**Workflow:** send the setup message first, then design the three pages one at
a time (start simple, iterate per page). Link the `frontend/` subdirectory in
Claude Design so it reuses existing component patterns.

---

## 1. Project setup — send first

```
I'm designing the UI for PlayDesk — an AI-powered booking platform for a
game lounge: a gaming center with PS5 and Nintendo Switch stations, private
gaming rooms, and board-game tables. I'll build three pages one at a time:
a manual booking page, an AI chat front-desk, and a staff dashboard.

Visual direction — gaming-center vibe: energetic and modern, but still
trustworthy enough for taking bookings and payments. Dark UI base (deep
charcoal / near-black), one vivid neon accent (electric blue or magenta)
used sparingly for primary actions and highlights, crisp high-contrast type
with a bold display face for headings, card-based layouts with soft rounded
corners and subtle glow/elevation. Premium esports-lounge feel — not a
cluttered arcade, no gamer-cliché gradients. Responsive: the customer pages
(booking, chat) must work well on mobile; the staff dashboard is desktop-first.

I'll link my codebase so you can match existing structure — please reuse
component patterns where they exist. Ask me anything before generating.
```

---

## 2. Booking page — route `/`

```
Design the manual booking page (route `/`) for PlayDesk.

Goal: let a customer book a station in four guided steps on one page.
Audience: walk-in / online customers, often on mobile.

Layout — one scrollable page, four numbered step cards stacked; later steps
visually de-emphasized until reached:
1. Choose a resource — a grid of selectable resource cards. Each shows the
   name (e.g. "PS5 Station A"), a type tag (Console / Private Room /
   Board-game Table), capacity ("up to 4 players"), price per hour in CNY
   (¥58/hr), and small chips for consoles (controller count, featured titles
   like Elden Ring / FIFA 25).
2. Pick a date — a date picker.
3. Choose a time slot — a grid of available time-slot pills for the selected
   resource + date; clear empty state; a "suggested alternatives" row when
   the requested window is taken.
4. Confirm booking — a summary (resource, date, time) plus a short form for
   customer name and phone, and a primary "Confirm booking" button.

Include loading, empty, and error states for availability and confirm
(e.g. "that slot was just taken"). Keep the selected resource/date/slot
visually obvious throughout.
```

---

## 3. Chat page — route `/chat`

```
Design the AI front-desk chat page (route `/chat`) for PlayDesk.

Goal: a customer books or asks questions by chatting with an AI assistant
that streams its replies.
Audience: customers, often on mobile.

Layout — a focused chat screen: a transcript that fills the height, with a
message composer (text input + send button) pinned at the bottom.
- Bubbles: assistant on the left with an AI avatar, customer on the right.
- Streaming: the assistant message looks natural as text streams in token by
  token (a caret or typing shimmer).
- Tool-call hints: while the AI works, a subtle inline status pill inside the
  assistant bubble — "Checking availability…", "Looking up policy…" — that
  resolves into the answer. They appear and disappear mid-message; the UI
  must never look frozen.
- Booking result: when the AI completes a booking, render a compact
  booking-confirmation card in the transcript (resource, date/time, ID).
- Error: a friendly inline error with a "Retry" button when the AI fails.

Show me the greeting/empty state (an assistant welcome message) and a
mid-stream state with a tool-call hint visible.
```

---

## 4. Admin dashboard — route `/admin`

```
Design the staff dashboard (route `/admin`) for PlayDesk.

Goal: let lounge staff monitor live AI conversations and see every booking
at a glance.
Audience: front-desk staff on a desktop monitor.

Layout — desktop-first, two regions:
- Live conversations panel — a list of active AI chat sessions; each shows
  the customer identifier, start time, and status (active / closed),
  active/newest first.
- All bookings table — every booking, newest first by created time. Columns:
  customer name, phone, resource, date & time range, status, source.
  - Status as a colored badge: pending, pending payment, confirmed, cancelled.
  - Source as a badge distinguishing "Manual" from "AI agent".
- A header strip with summary stat tiles (today's bookings, confirmed,
  pending payment).
- Data refreshes live — design a subtle "updated just now" indicator and a
  gentle highlight when a new booking row appears.

Include filters on the bookings table (status, date). Show loading and
empty states.
```

---

## Export & handoff

When a page looks right in Claude Design, use **"Handoff to Claude Code"** or
**"Export as standalone HTML" / `.zip`** and drop the output into the repo.
That export is the prerequisite for tasks #20–#22 — once it lands, the page
markup/components get wired to the generated API client and SSE hook from
[#19](https://github.com/Yuk1Neek0/PlayDesk/issues/19).

---

## 5. Polish pass — typography + motion

Iterate on the shipped UI, not redesign it. Send this after the original
handoff lands and the pages are live in `frontend/src/app/`.

```
We have PlayDesk — a dark, gaming-lounge booking UI built from your earlier
handoff. The design system is in place; this is a polish pass, not a redesign.

CURRENT FOUNDATION (keep all of it):
- Palette: near-black surfaces (#0a0b0e / #14161c / #1d2129), single cyan
  accent at oklch(0.78 0.16 200), text ramp #eef0f4 → #545a66.
- Type: Space Grotesk (display), Inter (body), JetBrains Mono (mono),
  wired through next/font in src/app/layout.tsx.
- Motion token: --t: 200ms cubic-bezier(.2,.65,.3,1).
- Radii: 8 / 12 / 16 / 22 px. Hairline borders at rgba(255,255,255, .06–.12).
- Pages: / (4-step booking flow with date strip + slot grid), /chat (AI
  front desk with streaming bubbles + "checking availability…" tool-call
  hints), /admin (live conversations + bookings table), /login.

WHAT TO IMPROVE:

1. Typography rhythm
   - Tighter type scale across the booking flow (currently feels uniform).
     Propose a 5-step ramp from hero to micro, with deliberate weight
     contrast — Space Grotesk for numerics and step headers, Inter
     everywhere else. Show the rendered hero on / and the chat header
     side by side.
   - Better tabular numerals on prices, booking IDs, and times. The /admin
     bookings table and the booking confirmation card both have ¥ amounts
     and HH:MM ranges that should align by column.
   - One opinionated detail font change is welcome if it sharpens the
     gaming-lounge feel — propose it, don't ship it blind.

2. Motion / micro-interactions (use --t and the existing easing token)
   - Page-enter fade-up for the booking page hero (~12px translateY).
   - Step-to-step scroll on / : a subtle highlight ring on the newly-active
     step (cyan glow that pulses once, then settles).
   - Date strip: slot cells should fade in staggered (~30ms apart) when the
     availability response lands. Booked cells get a quiet diagonal-stripe
     fade-in so users register them without alarm.
   - Chat bubbles: assistant tokens type in (no cursor blinker — token
     opacity ramp). Tool-call hint chips slide up from the composer's edge
     and fade out when the call resolves.
   - Confirmation view: the success stamp does one quiet scale-in (0.96 → 1)
     with the cyan glow, then everything else settles. No celebration
     overkill.
   - Buttons: keep the existing color treatment, but add a 1px press-down
     translate on :active and a soft cyan glow rise on :hover for primary.

3. /admin polish
   - Newest-first booking rows should land with a brief left-edge cyan flash
     (3px stripe fading in over 400ms then out) when a new booking arrives
     from a chat session — to make the live-update feel earned.

CONSTRAINTS:
- Stay on the existing CSS variables; new colors must be derivable from
  them. Do not introduce a second accent.
- No motion longer than 400ms on first paint; nothing blocking input.
- Respect prefers-reduced-motion (suppress fades and slides; keep opacity
  cross-fades only).
- Output as a React handoff (App-Router-compatible client components) +
  CSS additions to playdesk.css. Keep the pd-* class naming and the
  existing component shapes from src/app/page.tsx, src/app/chat/page.tsx,
  src/app/admin/page.tsx.

DELIVERABLE:
- Updated playdesk.css with the new motion tokens and keyframes
- Patched JSX for the four pages with the new class hooks
- A short "what changed and why" note per page
```

After the bundle returns:

1. Drop CSS additions into `frontend/src/app/playdesk.css`, JSX patches into
   the matching `frontend/src/app/*/page.tsx` files.
2. Run the Playwright suite (`PLAYDESK_LLM=1 npm run e2e` from `frontend/`).
   The calendar-today, manual-book-then-ask-AI, and admin assertions all
   key off `.pd-*` classes — if a class name changes, fix the selector, not
   the design.
3. Check DevTools "rendering → paint flashing" to confirm no layout thrash.
4. Verify `prefers-reduced-motion: reduce` in DevTools "rendering" — slides
   and translates should suppress; opacity cross-fades stay.
