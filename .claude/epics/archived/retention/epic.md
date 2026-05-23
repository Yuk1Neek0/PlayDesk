---
name: retention
status: completed
created: 2026-05-23T04:27:55Z
updated: 2026-05-23T14:10:41Z
progress: 100%
prd: .claude/prds/retention.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/77
---

# Epic: retention

## Overview

Add `Customer` + `CustomerNote` models, link `Booking.customer` (with backfill from existing name/phone strings), normalise phones via a shared helper, and ship a `/admin/customers` list + detail page. Foundational for the rest of the COSReady-shaped surface.

## Architecture Decisions

- **Phone is the dedup key, normalised to E.164.** Email is optional and ignored for dedup in v3. A single `core.phone.normalize_phone()` helper is used by booking creation, the SMS adapter (cross-slice), and the lookup-or-create logic — so two different code paths cannot disagree on what "the same phone" means.
- **`Customer` is scoped per `Store`.** The unique constraint is `(store_id, phone)`. A phone number can exist as one customer per store, not globally — matches the multi-store data model already in place.
- **Backfill is data-only and reversible.** The data migration populates `Booking.customer_id` from `customer_phone`; we keep the legacy `customer_name` / `customer_phone` columns on `Booking` for one release so nothing breaks.
- **Counters via signal, not denormalised join.** `Customer.total_visits` and `last_visit_at` are updated by a `post_save` signal on `Booking` — so the admin list query is one SELECT, no aggregate per row.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/customers/page.tsx` — list view (search + paginated table).
- `frontend/src/app/admin/customers/[id]/page.tsx` — detail view (profile + visits + notes).
- `frontend/src/components/customer-note.tsx` — single note + "add note" form.
- Reuse existing `pd-*` styles — no new CSS file.

### Backend Services
- `backend/core/migrations/000X_customer_and_note.py` — adds `Customer`, `CustomerNote`, and `Booking.customer` FK (nullable initially).
- `backend/core/migrations/000Y_backfill_booking_customer.py` — data migration; for each Booking with `customer_phone`, find-or-create `Customer` and set `customer_id`.
- `backend/core/models.py` — extend with the new models + a unique index on `(store_id, phone)`.
- `backend/core/phone.py` — `normalize_phone(raw, country='CA')` returning E.164 (or `None` if unparseable).
- `backend/core/signals.py` — booking-save signal that maintains the counter fields.
- `backend/api/admin_customers.py` — DRF list / retrieve views + serializer; search by name (case-insensitive) and phone (normalised).
- `backend/agent_tools/tools.py::create_booking` — call lookup-or-create on every booking creation.

### Infrastructure
- New pip dep: `phonenumbers` (industry-standard E.164 normalisation).
- No env-var changes.

## Implementation Strategy

Schema first, then the helper + signals, then the API + frontend in parallel.

## Task Breakdown Preview

- 001 — Migration: Customer + CustomerNote + Booking.customer FK
- 002 — Phone normalisation helper + tests + adoption inside booking creation
- 003 — Backfill data migration (lookup-or-create from existing customer_phone)
- 004 — Booking signal: maintain total_visits + last_visit_at
- 005 — Admin endpoints: list / retrieve / search + add-note POST
- 006 — Admin frontend: /admin/customers + /admin/customers/[id]

## Dependencies

- Hard: none.
- Soft: `multi-channel` SMS adapter reuses `normalize_phone()` once both are in main.
- Soft: `one-qr` clicks can credit a customer once `Customer` exists; otherwise events are anonymous.

## Success Criteria (Technical)

- Migration applies clean forward + reverse; backfill is idempotent.
- A second booking with the same normalised phone resolves to the same `Customer` row 100% of the time.
- Admin search p95 <300ms over 50 000 customers (verified with a perf fixture).
- Existing 157-test backend suite passes; ≥8 new tests cover dedup, normalisation, signals, search, and the lookup-or-create path.

## Estimated Effort

- ~3 days for one developer.
- Critical path: 001 (schema) → 002 (helper) → 003 (backfill). Then 004 / 005 / 006 in parallel.

## Tasks Created
- [ ] 001.md - Migration: Customer + CustomerNote + Booking.customer FK (parallel: false)
- [ ] 002.md - Phone normalisation helper + adoption (parallel: true)
- [ ] 003.md - Backfill data migration from existing customer_phone (parallel: false, conflicts with 002)
- [ ] 004.md - Booking signal: maintain Customer counters (parallel: true)
- [ ] 005.md - Admin endpoints: list / retrieve / search / add-note (parallel: true)
- [ ] 006.md - Admin frontend: /admin/customers + detail page (parallel: true)

Total tasks: 6
Parallel tasks: 4
Sequential tasks: 2
Estimated total effort: 22 hours
