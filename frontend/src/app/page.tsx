"use client";

// Booking page — guided 4-step flow: resource → date → time → confirm.
// UI ported from the Claude Design handoff; data is wired to the live
// backend through the generated REST client (src/lib/api.ts) — resources,
// availability, and booking creation are all real API calls. This completes
// task #20.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Ref } from "react";

import { Icon, ResourceArt, RESOURCE_TYPE_LABEL, fmtFullDate, isoDate } from "@/components/pd-ui";
import { HOURS, type Resource, type ResourceMeta, type ResourceType } from "@/lib/pd-data";
import {
  ApiError,
  createBooking,
  getResourceAvailability,
  listResources,
  type BookingCreate,
  type Resource as ApiResource,
} from "@/lib/api";
import { isoAt, pad, storeToday, toSlotData, type SlotData } from "@/lib/booking-availability";

type ConfirmState = "idle" | "loading" | "success" | "error";
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

export default function BookingPage() {
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

  // Load the resource catalogue from the API once.
  useEffect(() => {
    let cancelled = false;
    listResources()
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
  }, []);

  // Load availability whenever the resource or date changes.
  useEffect(() => {
    if (!resource) return;
    let cancelled = false;
    setAvailability({ loading: true, error: false, data: null });
    setSlot(null);
    getResourceAvailability(resource.id, isoDate(date))
      .then((resp) => {
        if (!cancelled) setAvailability({ loading: false, error: false, data: toSlotData(resp) });
      })
      .catch(() => {
        if (!cancelled) setAvailability({ loading: false, error: true, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [resource, date]);

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
    const body: BookingCreate = {
      resource_id: resource.id,
      customer_name: name,
      customer_phone: phone,
      start_time: isoAt(date, startHour),
      end_time: isoAt(date, startHour + duration),
      source: "manual",
    };
    createBooking(body)
      .then((booking) => {
        setConfirmedBooking({
          id: booking.id,
          resource,
          date,
          slot,
          end: `${pad((startHour + duration) % 24)}:00`,
          duration,
          name,
          phone,
          total: (parseFloat(resource.price_per_hour) * duration).toFixed(0),
        });
        setConfirmState("success");
      })
      .catch((err) => {
        setConfirmState("error");
        setErrorMsg(
          err instanceof ApiError && err.status === 409
            ? "That slot was just taken. Try a nearby time."
            : "Something went wrong creating your booking. Please try again.",
        );
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

  if (confirmState === "success" && confirmedBooking) {
    return <ConfirmationView booking={confirmedBooking} onReset={reset} />;
  }

  const total = resource
    ? (parseFloat(resource.price_per_hour) * duration).toFixed(0)
    : "—";

  return (
    <div className="pd-page pd-page--booking">
      <header className="pd-page-head">
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
  // A slot is usable only if `duration` consecutive hours are all free.
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
