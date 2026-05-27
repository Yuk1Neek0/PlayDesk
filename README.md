<h1 align="center">PlayDesk</h1>

<p align="center">
  <strong>The AI front desk for game lounges — bookings, payments, check-in, retention. All from one chat.</strong>
  <br />
  <em>PS5 · Switch · board games · private rooms.</em>
</p>

<p align="center">
  <a href="#-quickstart"><img src="https://img.shields.io/badge/Quickstart-blue" alt="Quickstart" /></a>
  <a href="#-under-the-hood"><img src="https://img.shields.io/badge/Architecture-8A2BE2" alt="Architecture" /></a>
  <img src="https://img.shields.io/badge/Django-4.x-092E20" alt="Django 4" />
  <img src="https://img.shields.io/badge/Next.js-App_Router-000000" alt="Next.js" />
  <img src="https://img.shields.io/badge/Postgres-pgvector-336791" alt="Postgres + pgvector" />
  <img src="https://img.shields.io/badge/Stripe-Connect-635BFF" alt="Stripe" />
  <img src="https://img.shields.io/badge/Twilio-SMS_·_WhatsApp_·_Voice-F22F46" alt="Twilio" />
</p>

<!-- DEMO GIF -->
<p align="center">
  <img src="docs/assets/demo.gif" alt="PlayDesk demo — AI front desk booking flow" width="800" />
</p>
<!-- /DEMO GIF -->

---

**It's Friday night.** The lounge is packed. The phone rings — someone wants to know if Station 3 is free at 9. A walk-in is asking about your deposit policy. Your staff is paging you because PS5-4 won't pair a controller. You can't be in three places at once.

PlayDesk can. It's an AI front desk that takes the booking, quotes the deposit, takes the deposit, sends the confirmation, prints the check-in QR, nudges the customer the morning of, and — when they don't come back in 60 days — pings them with a reactivation offer. **You run the lounge. PlayDesk runs the desk.**

> The goal isn't an AI that impresses you by being clever — it's an AI that quietly knows your policies, your prices, and your calendar, and just gets the booking done.

---

## ✨ Features

### Talk to the desk

A streaming agent loop with tool use. Customers chat in plain English (or 中文) and the agent checks live availability, quotes pricing from your rule engine, answers policy questions from your knowledge base, and creates the booking — all over a single SSE stream. Falls back gracefully when the LLM is offline.

### Book without the chat

A branded customer flow at `/s/<your-store>/book` for guests who'd rather click than type. Same pricing engine, same overlap-safe Postgres constraint, same Stripe-backed deposit — just a different surface.

### Get paid

Stripe Connect onboarding per store, deposit + balance flow, webhook-driven payment status, automatic refund matrix on cancellations (full / partial / none based on cancellation lead time), receipts via SMS + email, and an admin payments ledger.

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>🎟️ One QR, many actions</h3>
      <p>A single store QR routes to booking, check-in, account, or a campaign-of-the-day — driven by a per-store landing config you edit in the admin.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🔁 Rotating check-in</h3>
      <p>A short-lived QR rotates every N minutes — staff scans it on the floor, customers self-check-in without anyone juggling a master link.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>⭐ Memberships & rewards</h3>
      <p>Tiered membership, point ledger per booking, redemption flow, tier badges on the customer QR landing — built on a real transaction log, not a counter.</p>
    </td>
    <td width="50%" valign="top">
      <h3>📨 Campaigns & outbound</h3>
      <p>Define segments in a small DSL, schedule SMS or WhatsApp blasts with quiet-hours and STOP-handling, and watch the per-recipient state in the run dashboard.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>📈 Retention scoring</h3>
      <p>Customer churn score + cohort filters (e.g. <code>re_engagement_60d</code>) feed straight into campaign segments. The customers most likely to drift are one click away.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🏬 Multi-location</h3>
      <p>Switch between stores in the admin nav. Every endpoint and view is scoped by request middleware — cross-store leakage is rejected at the boundary, not in templates.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>👤 Customer portal</h3>
      <p>OTP-login at <code>/s/&lt;slug&gt;/account</code> — bookings, reschedule, cancel-with-refund, membership balance, redeemed rewards. One tab per concern.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🛡️ Staff auth, baked in</h3>
      <p>All <code>/api/admin/*</code> sits behind <code>StaffOnlyMiddleware</code>. CSRF is wired end-to-end. There is no "spoof the localStorage flag" path — the e2e suite proves it.</p>
    </td>
  </tr>
</table>

---

## 🚀 Quickstart

Requires Docker Desktop.

```bash
cp .env.example .env      # fill in any API keys you want to test against
docker compose up         # boots db (pgvector) + backend + frontend
```

- **Customer hub:** http://localhost:3000
- **Admin:** http://localhost:3000/admin (sign in via `/staff/login`)
- **Backend API:** http://localhost:8000

Seed data ships with two demo stores — **PlayDesk Flagship** and **PlayDesk North** — so you can exercise multi-location from the first boot. Switch between them in the admin nav.

```bash
docker compose exec backend python manage.py seed_data
```

---

## 🛠️ Development

**Backend** (from `backend/`):
```bash
pip install -r requirements.txt -r requirements-dev.txt
python manage.py migrate          # needs the Compose `db` service running
python manage.py seed_data
pytest                            # 800+ tests
ruff check . && ruff format --check .
```

**Frontend** (from `frontend/`):
```bash
npm install
npm run lint && npm run typecheck && npm test && npm run build
npm run e2e                       # Playwright suites for booking, portal, check-in, retention, multi-location
```

---

## 🔧 Under the Hood

### Postgres enforces the invariants

Booking overlap is rejected by a Postgres `EXCLUDE USING gist` constraint (with `btree_gist`), not by application code. There is no race window. Tests prove the database does the rejecting.

### RAG ≠ tools — and the agent knows the difference

Unstructured questions ("do you allow outside food?", "what consoles do you have?") go through pgvector-backed retrieval. Structured questions ("is Station 3 free Saturday at 9?", "how much for 2 hours on a private room?") go through typed tools that hit the database directly. The agent picks the right lane; the system prompt enforces it.

### Hand-rolled agent loop with streaming + tool use

Server-sent events to the browser, tool calls round-tripped server-side, streaming partial assistant tokens. The full SSE contract is frozen in `docs/contracts/sse-protocol.md` so the frontend and the agent can evolve independently.

### Per-request store resolution

`CurrentStoreMiddleware` resolves the active store from subdomain, slug, or session and exposes it as `request.store`. Every queryset filters by it. Every admin endpoint enforces it. Cross-store reads return 404 instead of leaking — and there's a cross-slice e2e test that would have caught it if they didn't.

### Pluggable pricing rules

A small `RuleStrategy` ABC with a registry. Each store composes its own pricing — peak / off-peak, day-of-week, member discount, deposit ratio. The compute_quote engine and the agent's `quoted_price` tool both go through the same code path. There is no "pricing in the frontend."

### Channel adapters

Twilio SMS, Twilio WhatsApp, Twilio Voice (TwiML), and the outbound pipeline all sit behind a `ChannelAdapter` / `OutboundChannelAdapter` ABC. Adding a new channel is one class. The send pipeline does the state machine — queued → sent → delivered / failed — with quiet-hours and opt-out applied before the adapter sees the message.

---

## 🗺️ Repository Layout

| Path | Contents |
|------|----------|
| `backend/` | Django 4 + DRF — `core`, `billing`, `campaigns`, `outbound`, `pricing`, `checkin`, `agent`, `rag` |
| `frontend/` | Next.js (App Router) + Tailwind — `/`, `/chat`, `/qr/[slug]`, `/s/[slug]/{book,account}`, `/c-in`, `/c/[token]`, `/admin/*`, `/staff/login` |
| `docs/contracts/` | Frozen interface contracts: OpenAPI, SSE protocol, KB format, eval format |
| `knowledge-base/` | RAG source content (English + 中文) |
| `docker-compose.yml` | `db` (pgvector), `backend`, `frontend` (with a dev override for hot-reload) |
| `.claude/` | CCPM workflow — PRDs, epics, tasks (archived per release under `archived/`) |
| `cosready_demo_dev_plan.md` | The product & development plan |

---

## 📋 How the Project is Run

PlayDesk is built with the **CCPM** workflow (`.claude/skills/ccpm`): every feature is a PRD → an epic → a batch of GitHub issues → parallel agents → archived. Each release leaves behind a paper trail under `.claude/epics/archived/` showing exactly what shipped, why, and which tests prove it. CI lints, type-checks, and tests both stacks against a real pgvector Postgres service plus a separate integrity workflow for LLM-touching evals.

If you're new to the codebase, the shortest path to context is:

1. Read `cosready_demo_dev_plan.md` for the product story.
2. Skim `.claude/epics/archived/` — each folder is a shipped feature with its tasks.
3. Read the frozen contracts in `docs/contracts/`.

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Run the tests: `pytest` (backend), `npm run lint && npm run typecheck && npm test && npm run build` (frontend)
4. Open a pull request

For anything bigger than a one-file change, open an issue first — we plan in CCPM and would rather decompose together than rework later.

---

<p align="center">
  <strong>Stop running the desk. Start running the lounge.</strong>
</p>
