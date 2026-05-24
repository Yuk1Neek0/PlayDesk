"use client";

// Multi-step client for the rotating in-store check-in flow.
//
// State machine:
//   phone        → POST /api/c-in/request-otp/      → otp
//   otp          → POST /api/c-in/verify-and-find/  → matches
//   matches      → switch on bookings.length:
//                   0  → walk-in card
//                   1  → single-match confirm
//                   2+ → disambiguation list
//   any-booking → POST /api/c-in/check-in/          → confirmation
//
// Errors render inline; the customer can always restart with the
// "Use a different number" button. Identity is the phone — no
// persistent session, just the cache flag the backend sets on
// verify-and-find.

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { customerFetch } from "@/lib/customer-fetch";
import type { StoreBrand } from "@/lib/store-brand";

export interface CheckinBooking {
  id: number;
  resource_name: string;
  start_time: string;
  end_time: string;
  status: string;
  checked_in_at: string | null;
  customer_name: string;
  can_check_in: boolean;
}

interface VerifyResponse {
  bookings: CheckinBooking[];
  store_slug: string;
  store_name: string;
}

type Step = "phone" | "otp" | "matches" | "confirmation";

interface Props {
  brand: StoreBrand;
  storeSlug: string;
  storeName: string;
  keyValue: string;
}

function firstName(full: string): string {
  return (full || "").trim().split(/\s+/)[0] || "there";
}

function formatTimeRange(startISO: string, endISO: string): string {
  try {
    const start = new Date(startISO);
    const end = new Date(endISO);
    const opts: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" };
    return `${start.toLocaleTimeString(undefined, opts)}–${end.toLocaleTimeString(
      undefined,
      opts,
    )}`;
  } catch {
    return "";
  }
}

export default function RotatingCheckinClient({
  brand,
  storeSlug,
  storeName,
  keyValue,
}: Props) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [bookings, setBookings] = useState<CheckinBooking[]>([]);
  const [confirmed, setConfirmed] = useState<CheckinBooking | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(0);

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = window.setTimeout(() => setResendIn((n) => n - 1), 1000);
    return () => window.clearTimeout(t);
  }, [resendIn]);

  function reset() {
    setPhone("");
    setCode("");
    setBookings([]);
    setConfirmed(null);
    setError(null);
    setStep("phone");
  }

  async function requestOtp() {
    setError(null);
    setBusy(true);
    try {
      await customerFetch(storeSlug, "/api/c-in/request-otp/", {
        method: "POST",
        body: JSON.stringify({ key: keyValue, phone }),
      });
      setStep("otp");
      setResendIn(60);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setError("Too many requests. Please wait 60 seconds and try again.");
      } else if (e instanceof ApiError && e.status === 410) {
        setError("This code expired. Please scan the QR again.");
      } else {
        setError("Connection problem — please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp() {
    setError(null);
    setBusy(true);
    try {
      const resp = await customerFetch<VerifyResponse>(
        storeSlug,
        "/api/c-in/verify-and-find/",
        {
          method: "POST",
          body: JSON.stringify({ key: keyValue, phone, code }),
        },
      );
      setBookings(resp.bookings);
      setStep("matches");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setError("Wrong code, please try again.");
      } else if (e instanceof ApiError && e.status === 410) {
        setError("This code expired. Please scan the QR again.");
      } else if (e instanceof ApiError && e.status === 429) {
        setError("Too many attempts. Please request a new code.");
      } else {
        setError("Connection problem — please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function checkIn(bookingId: number) {
    setError(null);
    setBusy(true);
    try {
      const resp = await customerFetch<CheckinBooking>(
        storeSlug,
        "/api/c-in/check-in/",
        {
          method: "POST",
          body: JSON.stringify({ key: keyValue, phone, booking_id: bookingId }),
        },
      );
      setConfirmed(resp);
      // Remove the checked-in booking from the remaining list so the
      // customer can do the next one without re-verifying. The cache
      // flag was consumed on the backend, so further check-ins would
      // need a re-verify — surface that copy on the success screen.
      setBookings((prev) => prev.filter((b) => b.id !== bookingId));
      setStep("confirmation");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setError("Verification expired. Please re-enter your phone and code.");
        setStep("phone");
        setCode("");
      } else if (e instanceof ApiError && e.status === 410) {
        setError("This code expired. Please scan the QR again.");
      } else {
        setError("Connection problem — please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  const accent = brand.accent ?? null;
  const wrapperStyle: React.CSSProperties | undefined = accent
    ? ({ "--pd-accent": accent, "--accent": accent } as React.CSSProperties)
    : undefined;

  return (
    <main
      className="pd-checkin-page"
      style={wrapperStyle}
      data-testid="rotating-checkin-root"
    >
      <section className="pd-checkin-card">
        <header className="pd-checkin-head">
          {brand.logo_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={brand.logo_url} alt="" className="pd-checkin-logo" />
          )}
          <div className="pd-checkin-store">{brand.name || storeName}</div>
        </header>

        <div className="pd-checkin-body">
          {step === "phone" && (
            <>
              <div className="pd-checkin-greeting">Welcome!</div>
              <p className="pd-page-sub">
                Enter your phone number — we&apos;ll text you a code to confirm.
              </p>
              <label className="pd-field">
                <span className="pd-field-label">Phone number</span>
                <input
                  className="pd-input"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="+1 416 555 0199"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  disabled={busy}
                  data-testid="phone-input"
                />
              </label>
              {error && (
                <div className="pd-error" data-testid="phone-error">
                  <span className="pd-error-dot" /> {error}
                </div>
              )}
              <button
                className="pd-btn pd-btn--primary pd-btn--lg"
                disabled={!phone || busy}
                onClick={requestOtp}
                data-testid="phone-submit"
              >
                {busy ? "Sending…" : "Continue"}
              </button>
            </>
          )}

          {step === "otp" && (
            <>
              <div className="pd-checkin-greeting">Enter your code</div>
              <p className="pd-page-sub" data-testid="otp-sent">
                Code sent to {phone}. It expires in 10 minutes.
              </p>
              <label className="pd-field">
                <span className="pd-field-label">6-digit code</span>
                <input
                  className="pd-input pd-mono"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  disabled={busy}
                  data-testid="otp-input"
                />
              </label>
              {error && (
                <div className="pd-error" data-testid="otp-error">
                  <span className="pd-error-dot" /> {error}
                </div>
              )}
              <button
                className="pd-btn pd-btn--primary pd-btn--lg"
                disabled={code.length !== 6 || busy}
                onClick={verifyOtp}
                data-testid="otp-submit"
              >
                {busy ? "Verifying…" : "Verify"}
              </button>
              <button
                className="pd-btn pd-btn--ghost"
                disabled={resendIn > 0 || busy}
                onClick={requestOtp}
              >
                {resendIn > 0 ? `Resend in ${resendIn}s` : "Resend code"}
              </button>
              <button
                className="pd-btn pd-btn--ghost"
                disabled={busy}
                onClick={reset}
              >
                Use a different number
              </button>
            </>
          )}

          {step === "matches" && bookings.length === 0 && (
            <div data-testid="walkin-card">
              <div className="pd-checkin-greeting">Hi {firstName(phone)},</div>
              <div className="pd-checkin-status pd-checkin-status--walkin">
                No bookings found on this phone today — please see staff to register a
                walk-in session.
              </div>
              <button className="pd-btn pd-btn--ghost" onClick={reset}>
                Start over
              </button>
            </div>
          )}

          {step === "matches" && bookings.length === 1 && (
            <div data-testid="single-match">
              <div className="pd-checkin-greeting">
                Welcome back, {firstName(bookings[0].customer_name)}!
              </div>
              <div className="pd-checkin-context">
                <div className="pd-checkin-resource">{bookings[0].resource_name}</div>
                <div className="pd-checkin-time">
                  {formatTimeRange(bookings[0].start_time, bookings[0].end_time)}
                </div>
              </div>
              {error && (
                <div className="pd-error">
                  <span className="pd-error-dot" /> {error}
                </div>
              )}
              <button
                className="pd-btn pd-btn--primary pd-btn--lg"
                disabled={busy}
                onClick={() => checkIn(bookings[0].id)}
                data-testid="single-checkin-btn"
              >
                {busy ? "Checking you in…" : "I'm here"}
              </button>
            </div>
          )}

          {step === "matches" && bookings.length > 1 && (
            <div data-testid="multi-match">
              <div className="pd-checkin-greeting">
                Welcome back, {firstName(bookings[0].customer_name)}!
              </div>
              <p className="pd-page-sub">Which booking are you here for?</p>
              {error && (
                <div className="pd-error">
                  <span className="pd-error-dot" /> {error}
                </div>
              )}
              <ul className="pd-checkin-list">
                {bookings.map((b) => (
                  <li key={b.id} className="pd-checkin-list-item">
                    <div>
                      <div className="pd-checkin-resource">{b.resource_name}</div>
                      <div className="pd-checkin-time">
                        {formatTimeRange(b.start_time, b.end_time)}
                      </div>
                    </div>
                    <button
                      className="pd-btn pd-btn--primary"
                      disabled={busy}
                      onClick={() => checkIn(b.id)}
                      data-testid={`multi-checkin-${b.id}`}
                    >
                      Check in
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {step === "confirmation" && confirmed && (
            <div data-testid="confirmation">
              <div className="pd-checkin-greeting">
                Welcome, {firstName(confirmed.customer_name)}!
              </div>
              <div className="pd-checkin-status pd-checkin-status--checked_in">
                ✓ Checked in — enjoy your session.
              </div>
              <div className="pd-checkin-context">
                <div className="pd-checkin-resource">{confirmed.resource_name}</div>
                <div className="pd-checkin-time">
                  {formatTimeRange(confirmed.start_time, confirmed.end_time)}
                </div>
              </div>
              {bookings.length > 0 && (
                <>
                  <p className="pd-page-sub">
                    You have {bookings.length} more booking
                    {bookings.length === 1 ? "" : "s"}. Verify your code again to
                    check them in.
                  </p>
                  <button
                    className="pd-btn pd-btn--ghost"
                    onClick={() => {
                      setCode("");
                      setStep("otp");
                    }}
                  >
                    Check in another booking
                  </button>
                </>
              )}
              <button className="pd-btn pd-btn--ghost" onClick={reset}>
                Done
              </button>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
