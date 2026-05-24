"use client";

// Customer-facing booking page — store-scoped variant for the
// `/s/[slug]/book` route. Near-identical to the legacy `app/BookingPage.tsx`
// (which `app/page.tsx` now 302-redirects away from), with one difference:
// every API call goes through `customerFetch(storeSlug, ...)` so the
// `X-PD-Store-Slug` header is set from the URL segment. That guarantees
// the booking lands on the URL store regardless of any pd_store_slug
// cookie an admin tab may have set, or the alphabetically-first fallback.
//
// Deliberately does NOT import `listResources`, `getResourceAvailability`,
// or `createBooking` from `@/lib/api` — those route through `adminFetch`,
// which reads the admin StoreContext and would cross-leak (see comment in
// `customer-fetch.ts`). The three local helpers below issue scoped calls.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Ref } from "react";
import Link from "next/link";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import type { Stripe, StripeElements } from "@stripe/stripe-js";

import { Icon, ResourceArt, RESOURCE_TYPE_LABEL, fmtFullDate, isoDate } from "@/components/pd-ui";
import { HOURS, type Resource, type ResourceMeta, type ResourceType } from "@/lib/pd-data";
import {
  ApiError,
  withTrailingSlash,
  type AvailabilityResponse,
  type Booking,
  type BookingCreate,
  type PaginatedResources,
  type Resource as ApiResource,
} from "@/lib/api";
import { customerFetch } from "@/lib/customer-fetch";
import { isoAt, pad, storeToday, toSlotData, type SlotData } from "@/lib/booking-availability";
import { loadStripeFromKey } from "@/lib/stripe";
import type { StoreBrand } from "@/lib/store-brand";

// v9.1 — augmented booking-create response. When a deposit is required the
// backend's _maybe_open_deposit merges these fields into the BookingSerializer
// payload. When deposit_mode=none they're absent and the booking is already
// confirmed.
interface PaymentInitFields {
  requires_payment?: boolean;
  deposit_amount?: string;
  client_secret?: string | null;
  publishable_key?: string;
  configured?: boolean;
  error?: string;
}
type BookingCreateResponse = Booking & PaymentInitFields;

type ConfirmState = "idle" | "loading" | "payment" | "success" | "error";
type StepFilter = "all" | ResourceType;

interface ConfirmedBooking {
  id: number;
  resource: Resource;
  date: Date;
  slot: string;
  end: string;
  duration: number;
  name: string;
  phone: string;
  total: string;
}

interface ResourcesState {
  loading: boolean;
  error: boolean;
  data: Resource[];
}

interface AvailabilityState {
  loading: boolean;
  error: boolean;
  data: SlotData | null;
}

// Scoped REST shims — same shapes as @/lib/api but routed through
// customerFetch so the URL store wins. The single-source-of-truth `request()`
// in api.ts intentionally delegates to adminFetch (StoreContext-aware);
// customer pages don't mount that provider, so we issue three direct calls
// from here. Keeping them inline avoids a parallel admin/customer split of
// the entire typed client.
function listResourcesScoped(slug: string): Promise<PaginatedResources> {
  return customerFetch<PaginatedResources>(slug, withTrailingSlash("/api/resources"));
}

function getAvailabilityScoped(
  slug: string,
  id: number,
  date: string,
): Promise<AvailabilityResponse> {
  return customerFetch<AvailabilityResponse>(
    slug,
    withTrailingSlash(`/api/resources/${id}/availability?date=${encodeURIComponent(date)}`),
  );
}

function createBookingScoped(slug: string, body: BookingCreate): Promise<BookingCreateResponse> {
  return customerFetch<BookingCreateResponse>(slug, withTrailingSlash("/api/bookings"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// v9.1 — payment-status poll. Public endpoint (no auth), returns the
// booking's current payment_status + status. Polled after Stripe confirms
// the PaymentIntent so the UI can react when the webhook flips the row.
async function fetchPaymentStatusScoped(
  slug: string,
  bookingId: number,
): Promise<{ payment_status: string; status: string }> {
  return customerFetch(
    slug,
    withTrailingSlash(`/api/bookings/${bookingId}/payment-status`),
  );
}

// v8 pricing-rules: live quote for the selected (resource, slot, duration).
// Rendered below the time picker so the customer sees the breakdown before
// they confirm; the same total goes back as ``expected_total_amount`` on
// submit so the backend can 409 if a rule changed under us.
export interface QuoteLineItem {
  label: string;
  amount: string;
  rule_id: number | null;
}
export interface QuoteResponse {
  base_amount: string;
  line_items: QuoteLineItem[];
  total_amount: string;
  rule_snapshot: QuoteLineItem[];
}

function fetchQuoteScoped(
  slug: string,
  body: { resource_id: number; start_at: string; end_at: string },
): Promise<QuoteResponse> {
  return customerFetch<QuoteResponse>(slug, withTrailingSlash("/api/quote"), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// API `Resource` (freeform metadata) → the view model the design uses.
function toViewResource(r: ApiResource): Resource {
  return {
    id: r.id,
    type: r.type,
    name: r.name,
    capacity: r.capacity,
    price_per_hour: r.price_per_hour,
    metadata: (r.metadata ?? {}) as ResourceMeta,
  };
}

interface BookingPageProps {
  brand: StoreBrand;
  storeSlug: string;
}

export default function BookingPage({ brand, storeSlug }: BookingPageProps) {
  const [resourcesState, setResourcesState] = useState<ResourcesState>({
    loading: true,
    error: false,
    data: [],
  });
  const [resource, setResource] = useState<Resource | null>(null);
  const [filter, setFilter] = useState<StepFilter>("all");
  const [date, setDate] = useState<Date>(() => storeToday());
  const [slot, setSlot] = useState<string | null>(null);
  const [duration, setDuration] = useState(2);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [confirmedBooking, setConfirmedBooking] = useState<ConfirmedBooking | null>(null);
  const [availability, setAvailability] = useState<AvailabilityState>({
    loading: false,
    error: false,
    data: null,
  });
  // v8 pricing-rules — live quote for the current (resource, slot, duration).
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [quoteChanged, setQuoteChanged] = useState(false);
  // v9.1 — when the backend requires a deposit, the booking-create response
  // carries the PaymentIntent client_secret + publishable_key. We hold them
  // here while the customer completes the Stripe Elements step.
  const [pendingPayment, setPendingPayment] = useState<{
    bookingId: number;
    clientSecret: string;
    publishableKey: string;
    depositAmount: string;
  } | null>(null);

  // Load the resource catalogue from the API once.
  useEffect(() => {
    let cancelled = false;
    listResourcesScoped(storeSlug)
      .then((page) => {
        if (!cancelled) {
          setResourcesState({ loading: false, error: false, data: page.results.map(toViewResource) });
        }
      })
      .catch(() => {
        if (!cancelled) setResourcesState({ loading: false, error: true, data: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [storeSlug]);

  // Load availability whenever the resource or date changes.
  useEffect(() => {
    if (!resource) return;
    let cancelled = false;
    setAvailability({ loading: true, error: false, data: null });
    setSlot(null);
    getAvailabilityScoped(storeSlug, resource.id, isoDate(date))
      .then((resp) => {
        if (!cancelled) setAvailability({ loading: false, error: false, data: toSlotData(resp) });
      })
      .catch(() => {
        if (!cancelled) setAvailability({ loading: false, error: true, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [resource, date, storeSlug]);

  // v8 pricing-rules — fetch the live quote whenever the (resource, slot,
  // duration) triple changes. Falls back to ``null`` on error so the legacy
  // base * hours summary still renders.
  useEffect(() => {
    if (!resource || !slot) {
      setQuote(null);
      return;
    }
    let cancelled = false;
    const startHour = parseInt(slot, 10);
    fetchQuoteScoped(storeSlug, {
      resource_id: resource.id,
      start_at: isoAt(date, startHour),
      end_at: isoAt(date, startHour + duration),
    })
      .then((q) => {
        if (!cancelled) {
          setQuote(q);
          setQuoteChanged(false);
        }
      })
      .catch(() => {
        if (!cancelled) setQuote(null);
      });
    return () => {
      cancelled = true;
    };
  }, [resource, slot, duration, date, storeSlug]);

  const step1 = useRef<HTMLElement>(null);
  const step2 = useRef<HTMLElement>(null);
  const step3 = useRef<HTMLElement>(null);
  const step4 = useRef<HTMLElement>(null);
  const refs = { 1: step1, 2: step2, 3: step3, 4: step4 };

  function focusStep(n: 1 | 2 | 3 | 4) {
    requestAnimationFrame(() => {
      const el = refs[n].current;
      if (!el) return;
      const top = el.getBoundingClientRect().top + window.scrollY - 80;
      window.scrollTo({ top, behavior: "smooth" });
    });
  }

  function chooseResource(r: Resource) {
    setResource(r);
    setSlot(null);
    focusStep(2);
  }
  function chooseDate(d: Date) {
    setDate(d);
    setSlot(null);
    focusStep(3);
  }
  function chooseSlot(s: string) {
    setSlot(s);
    focusStep(4);
  }

  function submit() {
    if (!resource || !slot || !name || !phone) return;
    setConfirmState("loading");
    const startHour = parseInt(slot, 10);
    const body: BookingCreate & { expected_total_amount?: string } = {
      resource_id: resource.id,
      customer_name: name,
      customer_phone: phone,
      start_time: isoAt(date, startHour),
      end_time: isoAt(date, startHour + duration),
      source: "manual",
    };
    // v8 pricing-rules — optimistic concurrency. If the engine recomputes a
    // different total at submit time (rule edited between quote + submit),
    // the server returns 409 with the new quote so we can re-render the
    // breakdown and ask for confirmation.
    if (quote) body.expected_total_amount = quote.total_amount;

    createBookingScoped(storeSlug, body)
      .then((booking) => {
        // v9.1: deposit-required path. The backend created a PaymentIntent
        // and returned a client_secret; render Stripe Elements next.
        // configured=false means dev/test stub — skip Stripe and confirm
        // directly (the Payment row is already created as a test stub).
        const wantsPayment =
          booking.requires_payment === true &&
          booking.client_secret &&
          booking.publishable_key;
        if (wantsPayment) {
          setPendingPayment({
            bookingId: booking.id,
            clientSecret: booking.client_secret as string,
            publishableKey: booking.publishable_key as string,
            depositAmount: booking.deposit_amount ?? "0.00",
          });
          setConfirmedBooking({
            id: booking.id,
            resource,
            date,
            slot,
            end: `${pad((startHour + duration) % 24)}:00`,
            duration,
            name,
            phone,
            total: quote
              ? quote.total_amount
              : (parseFloat(resource.price_per_hour) * duration).toFixed(0),
          });
          setConfirmState("payment");
          return;
        }

        setConfirmedBooking({
          id: booking.id,
          resource,
          date,
          slot,
          end: `${pad((startHour + duration) % 24)}:00`,
          duration,
          name,
          phone,
          total: quote
            ? quote.total_amount
            : (parseFloat(resource.price_per_hour) * duration).toFixed(0),
        });
        setConfirmState("success");
      })
      .catch((err) => {
        setConfirmState("error");
        if (err instanceof ApiError && err.status === 409) {
          const body = err.body as { error?: string; new_quote?: QuoteResponse } | null;
          if (body?.error === "quote_changed" && body.new_quote) {
            setQuote(body.new_quote);
            setQuoteChanged(true);
            setErrorMsg(
              `Price changed — new total ¥${body.new_quote.total_amount}. Please confirm.`,
            );
            return;
          }
          setErrorMsg("That slot was just taken. Try a nearby time.");
          return;
        }
        setErrorMsg("Something went wrong creating your booking. Please try again.");
      });
  }

  function reset() {
    setConfirmState("idle");
    setConfirmedBooking(null);
    setResource(null);
    setSlot(null);
    setName("");
    setPhone("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const filteredResources = useMemo(
    () =>
      filter === "all"
        ? resourcesState.data
        : resourcesState.data.filter((r) => r.type === filter),
    [filter, resourcesState.data],
  );

  // A 14-day strip starting at today in the store's timezone.
  const dateStrip = useMemo(() => {
    const today = storeToday();
    const arr: Date[] = [];
    for (let i = 0; i < 14; i++) {
      const d = new Date(today);
      d.setDate(today.getDate() + i);
      arr.push(d);
    }
    return arr;
  }, []);

  if (confirmState === "payment" && confirmedBooking && pendingPayment) {
    return (
      <PaymentView
        booking={confirmedBooking}
        pending={pendingPayment}
        storeSlug={storeSlug}
        onPaid={() => setConfirmState("success")}
        onCancel={reset}
      />
    );
  }

  if (confirmState === "success" && confirmedBooking) {
    return <ConfirmationView booking={confirmedBooking} onReset={reset} />;
  }

  const total = quote
    ? quote.total_amount
    : resource
      ? (parseFloat(resource.price_per_hour) * duration).toFixed(0)
      : "—";

  const wrapperStyle: React.CSSProperties | undefined = brand.accent
    ? ({ "--pd-accent": brand.accent, "--accent": brand.accent } as React.CSSProperties)
    : undefined;

  return (
    <div className="pd-page pd-page--booking" style={wrapperStyle}>
      <header className="pd-page-head">
        <div className="pd-page-head-row">
          <div className="pd-brand-logo">
            {brand.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="pd-brand-logo-img"
                src={brand.logo_url}
                alt={brand.name}
              />
            ) : (
              <span className="pd-brand-mark" aria-hidden>
                <Icon.logo size={28} />
              </span>
            )}
          </div>
          <Link
            href={`/s/${encodeURIComponent(storeSlug)}/account`}
            className="pd-chip pd-chip--ghost"
          >
            My account
          </Link>
        </div>
        <div className="pd-eyebrow">Book a session</div>
        <h1 className="pd-page-title">
          Pick your station,
          <br />
          set your night.
        </h1>
        <p className="pd-page-sub">
          Four guided steps. Live availability. Pay at the door or by Stripe.
        </p>
      </header>

      {/* Step 1 — Resource */}
      <Step
        n={1}
        title="Choose a resource"
        active={!resource}
        done={!!resource}
        innerRef={step1}
        summary={resource ? `${resource.name} · ¥${parseInt(resource.price_per_hour, 10)}/hr` : null}
      >
        <div className="pd-tabs">
          {(
            [
              ["all", "All"],
              ["console", "Consoles"],
              ["room", "Private rooms"],
              ["table", "Board games"],
            ] as [StepFilter, string][]
          ).map(([k, label]) => (
            <button
              key={k}
              className={`pd-tab ${filter === k ? "is-active" : ""}`}
              onClick={() => setFilter(k)}
            >
              {label}
            </button>
          ))}
        </div>
        {resourcesState.loading && (
          <div className="pd-empty">Loading resources…</div>
        )}
        {resourcesState.error && (
          <div className="pd-error">
            <span className="pd-error-dot" />
            Couldn&apos;t load resources. Refresh to try again.
          </div>
        )}
        {!resourcesState.loading && !resourcesState.error && (
          <div className="pd-resource-grid">
            {filteredResources.map((r) => (
              <ResourceCard
                key={r.id}
                r={r}
                selected={resource?.id === r.id}
                onSelect={() => chooseResource(r)}
              />
            ))}
          </div>
        )}
      </Step>

      {/* Step 2 — Date */}
      <Step
        n={2}
        title="Pick a date"
        active={!!resource && !slot}
        done={!!resource}
        locked={!resource}
        innerRef={step2}
        summary={resource ? fmtFullDate(date) : null}
      >
        <div className="pd-date-strip" role="listbox">
          {dateStrip.map((d) => {
            const selected = isoDate(d) === isoDate(date);
            const isToday = isoDate(d) === isoDate(storeToday());
            return (
              <button
                key={d.toISOString()}
                className={`pd-date-cell ${selected ? "is-selected" : ""}`}
                onClick={() => chooseDate(d)}
              >
                <div className="pd-date-day">
                  {d.toLocaleDateString("en-GB", { weekday: "short" })}
                </div>
                <div className="pd-date-num">{d.getDate()}</div>
                <div className="pd-date-mon">
                  {d.toLocaleDateString("en-GB", { month: "short" })}
                  {isToday ? " · today" : ""}
                </div>
              </button>
            );
          })}
        </div>
      </Step>

      {/* Step 3 — Time slot */}
      <Step
        n={3}
        title="Choose a time"
        active={!!resource && !slot}
        done={!!slot}
        locked={!resource}
        innerRef={step3}
        summary={slot ? `${slot} – ${pad(parseInt(slot, 10) + duration)}:00 · ${duration}h` : null}
      >
        <div className="pd-duration">
          <span className="pd-label">Duration</span>
          <div className="pd-seg">
            {[1, 2, 3, 4].map((h) => (
              <button
                key={h}
                className={`pd-seg-item ${duration === h ? "is-active" : ""}`}
                onClick={() => setDuration(h)}
              >
                {h}h
              </button>
            ))}
          </div>
        </div>
        <SlotsGrid availability={availability} slot={slot} duration={duration} onPick={chooseSlot} />
        {slot && quote && (
          <QuoteBreakdown quote={quote} changed={quoteChanged} />
        )}
      </Step>

      {/* Step 4 — Confirm */}
      <Step n={4} title="Confirm booking" active={!!slot} locked={!slot} innerRef={step4}>
        <div className="pd-confirm">
          <div className="pd-summary">
            <div className="pd-summary-row">
              <span className="pd-summary-key">Resource</span>
              <span className="pd-summary-val">{resource?.name ?? "—"}</span>
            </div>
            <div className="pd-summary-row">
              <span className="pd-summary-key">Date</span>
              <span className="pd-summary-val">{resource ? fmtFullDate(date) : "—"}</span>
            </div>
            <div className="pd-summary-row">
              <span className="pd-summary-key">Time</span>
              <span className="pd-summary-val">
                {slot ? `${slot} – ${pad(parseInt(slot, 10) + duration)}:00 · ${duration}h` : "—"}
              </span>
            </div>
            <div className="pd-summary-row pd-summary-row--total">
              <span className="pd-summary-key">Total</span>
              <span className="pd-summary-val pd-mono">¥ {total}</span>
            </div>
          </div>
          <div className="pd-form">
            <label className="pd-field">
              <span className="pd-field-label">Your name</span>
              <input
                className="pd-input"
                placeholder="王小明 / Alice Wang"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={!slot}
              />
            </label>
            <label className="pd-field">
              <span className="pd-field-label">Phone</span>
              <input
                className="pd-input"
                placeholder="+86 138 0000 0000"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                disabled={!slot}
              />
            </label>
            {confirmState === "error" && (
              <div className="pd-error">
                <span className="pd-error-dot" />
                {errorMsg}
              </div>
            )}
            <button
              className="pd-btn pd-btn--primary pd-btn--lg"
              disabled={!slot || !name || !phone || confirmState === "loading"}
              onClick={submit}
            >
              {confirmState === "loading" ? (
                <>
                  <span className="pd-spinner" /> Confirming…
                </>
              ) : (
                <>Confirm booking · ¥{resource && slot ? total : "—"}</>
              )}
            </button>
            <p className="pd-fine">
              You&apos;ll get an SMS receipt. Cancel up to 2 h before start for a full refund.
            </p>
          </div>
        </div>
      </Step>
    </div>
  );
}

function Step({
  n,
  title,
  active,
  done,
  locked,
  summary,
  children,
  innerRef,
}: {
  n: number;
  title: string;
  active?: boolean;
  done?: boolean;
  locked?: boolean;
  summary?: string | null;
  children: React.ReactNode;
  innerRef: Ref<HTMLElement>;
}) {
  return (
    <section
      ref={innerRef}
      className={`pd-step ${active ? "is-active" : ""} ${done ? "is-done" : ""} ${locked ? "is-locked" : ""}`}
    >
      <header className="pd-step-head">
        <div className={`pd-step-num ${done ? "is-done" : ""}`}>
          {done ? <Icon.check size={14} /> : <span>{n}</span>}
        </div>
        <h2 className="pd-step-title">{title}</h2>
        {summary && <div className="pd-step-summary">{summary}</div>}
      </header>
      <div className="pd-step-body">{children}</div>
    </section>
  );
}

function ResourceCard({
  r,
  selected,
  onSelect,
}: {
  r: Resource;
  selected: boolean;
  onSelect: () => void;
}) {
  const titles = r.metadata.titles ?? r.metadata.featured ?? [];
  return (
    <button className={`pd-rcard ${selected ? "is-selected" : ""}`} onClick={onSelect}>
      <ResourceArt type={r.type} />
      <div className="pd-rcard-body">
        <div className="pd-rcard-row">
          <div className="pd-rcard-name">{r.name}</div>
          {selected && <Icon.check size={16} />}
        </div>
        <div className="pd-rcard-meta">
          <span className="pd-chip pd-chip--ghost">{RESOURCE_TYPE_LABEL[r.type]}</span>
          <span className="pd-chip pd-chip--ghost">up to {r.capacity}</span>
          {!!r.metadata.controller_count && (
            <span className="pd-chip pd-chip--ghost">{r.metadata.controller_count} pads</span>
          )}
          {r.metadata.projector && <span className="pd-chip pd-chip--ghost">projector</span>}
        </div>
        {titles.length > 0 && (
          <div className="pd-rcard-titles">
            {titles.slice(0, 3).map((t) => (
              <span key={t} className="pd-chip pd-chip--tag">
                {t}
              </span>
            ))}
          </div>
        )}
        <div className="pd-rcard-foot">
          <span className="pd-price">
            <span className="pd-mono">¥{parseInt(r.price_per_hour, 10)}</span>
            <span className="pd-price-sub">/hr</span>
          </span>
        </div>
      </div>
    </button>
  );
}

function SlotsGrid({
  availability,
  slot,
  duration,
  onPick,
}: {
  availability: AvailabilityState;
  slot: string | null;
  duration: number;
  onPick: (s: string) => void;
}) {
  if (availability.loading) {
    return (
      <div className="pd-slots-grid">
        {HOURS.map((h, i) => (
          <div
            key={h}
            className="pd-slot pd-slot--skel"
            style={{ "--i": i } as React.CSSProperties}
          />
        ))}
      </div>
    );
  }
  if (availability.error) {
    return (
      <div className="pd-error">
        <span className="pd-error-dot" />
        Couldn&apos;t load availability. Pick another date or try again.
      </div>
    );
  }
  if (!availability.data) {
    return <div className="pd-empty">Pick a resource and a date to see open slots.</div>;
  }

  const free = new Set(availability.data.available);
  const lastHour = 23 - (duration - 1);
  const usableFree = HOURS.filter((h) => {
    if (parseInt(h, 10) > lastHour) return false;
    for (let i = 0; i < duration; i++) {
      if (!free.has(`${pad(parseInt(h, 10) + i)}:00`)) return false;
    }
    return true;
  });
  const taken = HOURS.filter((h) => !free.has(h));

  if (usableFree.length === 0) {
    const suggestions = availability.data.suggestions;
    return (
      <div className="pd-empty">
        <strong>Fully booked at this duration.</strong>
        <p>Try a shorter session or a nearby date.</p>
        {suggestions.length > 0 && (
          <div className="pd-suggestions">
            {suggestions.map((s) => (
              <button key={s} className="pd-chip pd-chip--suggest" onClick={() => onPick(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="pd-slots">
      <div className="pd-slots-grid">
        {HOURS.map((h, i) => {
          const canPick = usableFree.includes(h);
          const isTaken = taken.includes(h);
          return (
            <button
              key={h}
              className={`pd-slot ${slot === h ? "is-selected" : ""} ${!canPick ? "is-disabled" : ""} ${isTaken ? "is-taken" : ""}`}
              style={{ "--i": i } as React.CSSProperties}
              disabled={!canPick}
              onClick={() => onPick(h)}
            >
              <span className="pd-slot-time">{h}</span>
              {isTaken && <span className="pd-slot-tag">booked</span>}
            </button>
          );
        })}
      </div>
      <div className="pd-legend">
        <span className="pd-legend-item">
          <i className="pd-dot pd-dot--free" /> Available
        </span>
        <span className="pd-legend-item">
          <i className="pd-dot pd-dot--taken" /> Booked
        </span>
        <span className="pd-legend-item">
          <i className="pd-dot pd-dot--sel" /> Selected
        </span>
      </div>
    </div>
  );
}

function ConfirmationView({
  booking,
  onReset,
}: {
  booking: ConfirmedBooking;
  onReset: () => void;
}) {
  return (
    <div className="pd-page pd-confirmed">
      <div className="pd-confirmed-card">
        <div className="pd-confirmed-stamp">
          <Icon.check size={28} />
        </div>
        <div className="pd-eyebrow pd-eyebrow--accent">Booking confirmed</div>
        <h1 className="pd-confirmed-title">See you at PlayDesk.</h1>
        <div className="pd-confirmed-grid">
          <div>
            <span className="pd-confirmed-key">Booking ID</span>
            <span className="pd-mono">#{booking.id}</span>
          </div>
          <div>
            <span className="pd-confirmed-key">Resource</span>
            <span>{booking.resource.name}</span>
          </div>
          <div>
            <span className="pd-confirmed-key">Date</span>
            <span>{fmtFullDate(booking.date)}</span>
          </div>
          <div>
            <span className="pd-confirmed-key">Time</span>
            <span className="pd-mono">
              {booking.slot} – {booking.end}
            </span>
          </div>
          <div>
            <span className="pd-confirmed-key">Name</span>
            <span>{booking.name}</span>
          </div>
          <div>
            <span className="pd-confirmed-key">Total</span>
            <span className="pd-mono">¥ {booking.total}</span>
          </div>
        </div>
        <div className="pd-confirmed-actions">
          <button className="pd-btn pd-btn--primary" onClick={onReset}>
            Make another booking
          </button>
          <button className="pd-btn pd-btn--ghost">Add to calendar</button>
        </div>
        <p className="pd-fine">
          A confirmation SMS will arrive at {booking.phone} momentarily.
        </p>
      </div>
    </div>
  );
}

// v9.1 — Stripe payment step. Renders Elements with the PaymentIntent
// client_secret from the booking-create response. After the customer
// confirms, polls `/api/bookings/{id}/payment-status/` until the webhook
// flips `payment_status` to `deposit_paid` (or 30s timeout).
function PaymentView({
  booking,
  pending,
  storeSlug,
  onPaid,
  onCancel,
}: {
  booking: ConfirmedBooking;
  pending: {
    bookingId: number;
    clientSecret: string;
    publishableKey: string;
    depositAmount: string;
  };
  storeSlug: string;
  onPaid: () => void;
  onCancel: () => void;
}) {
  const stripePromise = useMemo(
    () => loadStripeFromKey(pending.publishableKey),
    [pending.publishableKey],
  );

  if (!stripePromise) {
    return (
      <div className="pd-page pd-confirmed">
        <div className="pd-confirmed-card">
          <div className="pd-eyebrow">Payment unavailable</div>
          <h1 className="pd-confirmed-title">We couldn&apos;t reach Stripe.</h1>
          <p className="pd-fine">
            Your booking <span className="pd-mono">#{booking.id}</span> is on hold.
            Please contact staff to complete the deposit, or start over.
          </p>
          <div className="pd-confirmed-actions">
            <button className="pd-btn pd-btn--ghost" onClick={onCancel}>
              Start over
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="pd-page pd-confirmed">
      <div className="pd-confirmed-card">
        <div className="pd-eyebrow pd-eyebrow--accent">Pay deposit to confirm</div>
        <h1 className="pd-confirmed-title">
          Hold your slot — ¥{pending.depositAmount}
        </h1>
        <p className="pd-fine">
          Booking <span className="pd-mono">#{booking.id}</span> · {booking.resource.name}
          {" · "}
          {fmtFullDate(booking.date)} · {booking.slot} – {booking.end}
        </p>
        <Elements
          stripe={stripePromise}
          options={{ clientSecret: pending.clientSecret, appearance: { theme: "stripe" } }}
        >
          <PaymentForm
            bookingId={pending.bookingId}
            storeSlug={storeSlug}
            onPaid={onPaid}
            onCancel={onCancel}
          />
        </Elements>
      </div>
    </div>
  );
}

function PaymentForm({
  bookingId,
  storeSlug,
  onPaid,
  onCancel,
}: {
  bookingId: number;
  storeSlug: string;
  onPaid: () => void;
  onCancel: () => void;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePay(s: Stripe, e: StripeElements) {
    setSubmitting(true);
    setError(null);
    const result = await s.confirmPayment({
      elements: e,
      redirect: "if_required",
      confirmParams: {
        return_url: window.location.href,
      },
    });
    if (result.error) {
      setSubmitting(false);
      setError(result.error.message ?? "Payment failed. Try a different card.");
      return;
    }
    // PaymentIntent has succeeded client-side. The Stripe webhook will
    // flip the booking row's payment_status; poll until we see it.
    setSubmitting(false);
    setPolling(true);
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      try {
        const { payment_status } = await fetchPaymentStatusScoped(storeSlug, bookingId);
        if (payment_status === "deposit_paid" || payment_status === "paid_in_full") {
          onPaid();
          return;
        }
      } catch {
        // transient — keep polling
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    // Timeout: webhook hasn't arrived. The PaymentIntent succeeded
    // though, so the booking will flip eventually. Surface gracefully.
    setPolling(false);
    setError(
      "Payment confirmed but we're still syncing — please refresh in a moment, or contact staff.",
    );
  }

  return (
    <div className="pd-form" style={{ marginTop: 16 }}>
      <PaymentElement />
      {error && (
        <div className="pd-error" style={{ marginTop: 12 }}>
          <span className="pd-error-dot" /> {error}
        </div>
      )}
      <button
        className="pd-btn pd-btn--primary pd-btn--lg"
        disabled={!stripe || !elements || submitting || polling}
        onClick={() => {
          if (stripe && elements) handlePay(stripe, elements);
        }}
        style={{ marginTop: 16 }}
      >
        {submitting ? (
          <>
            <span className="pd-spinner" /> Authorising…
          </>
        ) : polling ? (
          <>
            <span className="pd-spinner" /> Confirming payment…
          </>
        ) : (
          <>Pay deposit</>
        )}
      </button>
      <button
        className="pd-btn pd-btn--ghost"
        onClick={onCancel}
        disabled={submitting || polling}
        style={{ marginTop: 8 }}
      >
        Cancel
      </button>
    </div>
  );
}

// v8 pricing-rules — small breakdown rendered below the time picker once
// a slot is selected. Mirrors the admin booking-detail's snapshot table
// shape so the customer-facing math matches what staff see.
function QuoteBreakdown({
  quote,
  changed,
}: {
  quote: QuoteResponse;
  changed: boolean;
}) {
  return (
    <div className="pd-summary" style={{ marginTop: 16 }} data-testid="pd-quote">
      {changed && (
        <div className="pd-error" style={{ marginBottom: 8 }}>
          <span className="pd-error-dot" /> Price updated — please review and confirm.
        </div>
      )}
      {quote.line_items.map((li, idx) => (
        <div className="pd-summary-row" key={`${li.label}-${idx}`}>
          <span className="pd-summary-key">{li.label}</span>
          <span className="pd-summary-val pd-mono">
            {li.amount.startsWith("-") ? "" : ""}¥{li.amount}
          </span>
        </div>
      ))}
      <div className="pd-summary-row pd-summary-row--total">
        <span className="pd-summary-key">Total</span>
        <span className="pd-summary-val pd-mono">¥{quote.total_amount}</span>
      </div>
    </div>
  );
}
