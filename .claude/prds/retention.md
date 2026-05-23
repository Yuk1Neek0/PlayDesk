---
name: retention
description: Add a Customer entity with profile, visit history, and notes so PlayDesk can support the retention-shaped product surface COSReady's website advertises.
status: backlog
created: 2026-05-23T04:27:55Z
---

# PRD: retention

## Executive Summary

PlayDesk's current data model carries the *transaction* — a booking with a customer's name and phone as bare strings — but not the *customer*. COSReady's website foregrounds customer retention (profiles, visit history, follow-ups, repeat-visit support) as a major differentiator over "calendar-only booking tools". Several other COSReady modules (rewards, memberships, marketing campaigns, One QR) all sit on top of a Customer entity.

This epic adds the Customer foundation: a `Customer` model with profile fields, a `Booking.customer` foreign key with auto-lookup-by-phone on creation, a `/admin/customers` list, and a `/admin/customers/[id]` detail page showing visit history and notes. It is deliberately scoped to the foundation; rewards / memberships / campaigns / One QR are separate slices that build on it.

## Problem Statement

Without a Customer entity, several COSReady-relevant features are structurally impossible:
- "Returning customer? Same Bob who booked last week?" — needs identity dedup.
- Rewards & memberships — need a stable identity to attach points / tier to.
- Follow-up workflows ("text Bob 24h after his appointment") — needs a target.
- Marketing campaigns ("Re-Engagement template") — needs a recipient set.
- "Visit history" / repeat-visit support — needs a JOIN target.

Today every booking just stores name + phone as strings, so two bookings from the same phone number look like two strangers to the system. Every retention story starts here.

## User Stories

- **As a customer**, when I book again with the same phone number, the system recognises me and links the new booking to my existing profile.
  - *Acceptance:* a second booking from `+1-416-555-0188` resolves to the same `Customer` row; admin sees both visits under one profile.
- **As staff**, I can open `/admin/customers`, search by name or phone, and click into a customer to see their full visit history, total spend, last visit date, and any notes I've left.
  - *Acceptance:* list page is paginated (50/page), search is debounced, detail page renders the visit table newest-first.
- **As staff**, I can add a short note to a customer's profile ("prefers PS5 over Switch", "needs accessible seating") that persists across visits.
  - *Acceptance:* notes are timestamped, attributed to the staff user who added them, and visible on every future visit's row.
- **As a customer (Chinese-speaking)**, my preferred language is remembered so future AI conversations open in 中文 by default.
  - *Acceptance:* `Customer.locale_pref` is captured on first booking; the agent reads it on subsequent turns.

## Functional Requirements

1. **`Customer` model**: `id`, `phone (unique, normalized E.164)`, `name`, `email (optional)`, `locale_pref ('en' | 'zh')`, `created_at`, `last_visit_at`, `total_visits (counter)`, `tags (JSON array of strings)`, `notes (one-to-many via `CustomerNote`)`.
2. **`CustomerNote` model**: `customer_id`, `author (Staff/User FK)`, `body`, `created_at`.
3. **`Booking.customer` FK** (nullable for backwards compat during migration), backfilled from `customer_phone` on existing rows. After backfill, `customer` is required for new bookings.
4. **Phone normalisation** — a single `normalize_phone()` helper used by booking creation, customer dedup, and Twilio adapter (cross-slice).
5. **Lookup-or-create on booking creation** — `core.bookings.create_booking()` (and the agent tool) resolves `Customer` by normalised phone, creating one if not found, updating `name` / `locale_pref` if the existing row had them blank.
6. **Admin list page** `/admin/customers`: search by name / phone, columns `name | phone | last visit | total visits | tags`, click-through.
7. **Admin detail page** `/admin/customers/[id]`: profile card (name / phone / email / locale), visit-history table (datetime, resource, status, source, amount), notes log with "add note" form.
8. **Visit-history endpoint** `/api/admin/customers/{id}/` returning the joined data (customer + bookings + notes) so the detail page is a single fetch.
9. **Counter maintenance** — `Customer.total_visits` and `last_visit_at` updated via signal when a `Booking` is created or its status changes.
10. **Bilingual support** — `locale_pref` consumed by the agent's existing language detector as a tie-breaker.

## Non-Functional Requirements

- One additive migration for the new models + one data migration for backfilling `Booking.customer`.
- All existing tests pass after the backfill — `customer_name` and `customer_phone` columns stay on `Booking` for one release cycle so nothing breaks.
- Search endpoint p95 latency <300ms over 50 000 customers (single GIN index on `phone` and a `lower(name)` index).
- `prefers-reduced-motion` respected on the customer detail page (the visit history fades in rather than slides).
- Phone normalisation is deterministic and idempotent — `normalize_phone(normalize_phone(x)) == normalize_phone(x)`.

## Success Criteria

- A second booking with the same normalised phone resolves to the same `Customer` row 100% of the time.
- A staff user can find any customer by partial name or partial phone in <2s.
- The detail page renders a customer with 100 visits without paginating below 30fps.
- The agent's existing language detector correctly defers to `Customer.locale_pref` when set, and otherwise falls back to the current message-based detection.
- No regression in the 157-test backend suite after the backfill.

## Constraints & Assumptions

- Customers are scoped per `Store` (multi-store data model already exists). A phone number can exist as one customer per store, not globally.
- Phone is the deduplication key — email is optional and not used for dedup in v3.
- No customer-facing self-service portal in v3 (no "log in to see my visits"). Customer surface is admin-only.

## Out of Scope

- Customer-facing portal / login.
- Marketing-list opt-in / GDPR export-delete workflow.
- Cross-store customer rollup.
- Loyalty tiers (separate slice).
- Outbound messaging (separate concern).

## Dependencies

- Hard: none — this is the foundation slice.
- Stream `one-qr` softly depends on this for awarding points to a stable customer identity; can ship a stub (phone-only) and migrate later if `retention` lags.
- Stream `multi-channel` is independent.
