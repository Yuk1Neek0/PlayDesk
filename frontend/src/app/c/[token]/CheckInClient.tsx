"use client";

// Client island for the public check-in page.
//
// Renders a centered card with the store brand, a friendly greeting,
// and either a big "I'm here" button (CONFIRMED) or a state-specific
// message (CANCELLED / CHECKED_IN / COMPLETED / PENDING_PAYMENT).
//
// On the button click we POST to `/api/c/<token>/check-in/`. The
// endpoint is idempotent — a re-tap returns the same payload — so we
// just trust the response and re-render with the new state.

import { useState } from "react";

import type { StoreBrand } from "@/lib/store-brand";

export interface CheckInPayload {
  booking_id: number;
  status: string;
  checked_in_at: string | null;
  customer_name: string;
  resource_name: string;
  start_time: string;
  end_time: string;
  store_slug: string;
  can_check_in: boolean;
  message: string;
}

interface Props {
  initial: CheckInPayload;
  brand: StoreBrand;
  token: string;
}

function firstName(full: string): string {
  return (full || "").trim().split(/\s+/)[0] || "there";
}

function formatTimeRange(startISO: string, endISO: string): string {
  try {
    const start = new Date(startISO);
    const end = new Date(endISO);
    const opts: Intl.DateTimeFormatOptions = {
      hour: "numeric",
      minute: "2-digit",
    };
    return `${start.toLocaleTimeString(undefined, opts)}–${end.toLocaleTimeString(
      undefined,
      opts,
    )}`;
  } catch {
    return "";
  }
}

export default function CheckInClient({ initial, brand, token }: Props) {
  const [state, setState] = useState<CheckInPayload>(initial);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCheckIn() {
    setSubmitting(true);
    setError(null);
    try {
      const resp = await fetch(`/api/c/${encodeURIComponent(token)}/check-in/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (resp.ok || resp.status === 200) {
        const next = (await resp.json()) as CheckInPayload;
        setState(next);
      } else {
        // Idempotent endpoint should never reject a checked-in re-tap;
        // a 409 here means CANCELLED / PENDING_PAYMENT etc — surface
        // whatever payload the server returned.
        try {
          const next = (await resp.json()) as CheckInPayload;
          setState(next);
        } catch {
          setError("Something went wrong. Please ask a staff member.");
        }
      }
    } catch {
      setError("Couldn't reach the server. Please try again or ask staff.");
    } finally {
      setSubmitting(false);
    }
  }

  const accent = brand.accent ?? null;
  const justCheckedIn = state.status === "checked_in" && state.checked_in_at !== null;

  return (
    <main
      className="pd-checkin-page"
      style={accent ? ({ ["--pd-accent" as string]: accent } as React.CSSProperties) : undefined}
    >
      <section className="pd-checkin-card" data-testid="checkin-card">
        <header className="pd-checkin-head">
          {brand.logo_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={brand.logo_url} alt="" className="pd-checkin-logo" />
          )}
          <div className="pd-checkin-store">{brand.name}</div>
        </header>

        <div className="pd-checkin-body">
          <div className="pd-checkin-greeting">
            {justCheckedIn ? (
              <>Welcome, {firstName(state.customer_name)}!</>
            ) : (
              <>Hi {firstName(state.customer_name)},</>
            )}
          </div>
          <div className="pd-checkin-context">
            <div className="pd-checkin-resource">{state.resource_name}</div>
            <div className="pd-checkin-time">
              {formatTimeRange(state.start_time, state.end_time)}
            </div>
          </div>

          {state.can_check_in ? (
            <>
              <button
                className="pd-checkin-btn"
                onClick={handleCheckIn}
                disabled={submitting}
                data-testid="checkin-button"
              >
                {submitting ? "Checking you in…" : "I'm here"}
              </button>
              {error && <div className="pd-checkin-error">{error}</div>}
            </>
          ) : (
            <div
              className={`pd-checkin-status pd-checkin-status--${state.status}`}
              data-testid="checkin-message"
            >
              {justCheckedIn ? `✓ ${state.message}` : state.message}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
