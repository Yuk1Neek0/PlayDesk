"use client";

// Customer-portal login (two-step: phone → 6-digit code).
//
// Both steps call the v7 backend `/api/customer-auth/...` endpoints via
// customerFetch so the X-PD-Store-Slug header binds the OTP / session
// to the URL store. On verify success the page is reloaded via
// router.refresh() — the server component re-runs, sees the new signed
// cookie, and renders the dashboard.
//
// Mobile-first: full-width inputs, single column, 16px font on inputs to
// avoid iOS zoom.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Icon } from "@/components/pd-ui";
import { ApiError } from "@/lib/api";
import { customerFetch } from "@/lib/customer-fetch";
import type { StoreBrand } from "@/lib/store-brand";

type Step = "phone" | "code";

interface LoginFormProps {
  brand: StoreBrand;
  storeSlug: string;
}

export default function LoginForm({ brand, storeSlug }: LoginFormProps) {
  const router = useRouter();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(0);

  // Resend cooldown ticker.
  useEffect(() => {
    if (resendIn <= 0) return;
    const t = window.setTimeout(() => setResendIn((n) => n - 1), 1000);
    return () => window.clearTimeout(t);
  }, [resendIn]);

  async function requestCode() {
    setError(null);
    setBusy(true);
    try {
      await customerFetch(storeSlug, "/api/customer-auth/request-code/", {
        method: "POST",
        body: JSON.stringify({ phone, store_slug: storeSlug }),
      });
      setStep("code");
      setResendIn(60);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setError("Too many requests. Please wait 60 seconds and try again.");
      } else if (e instanceof ApiError && e.status === 404) {
        setError("This store is not configured. Please contact staff.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode() {
    setError(null);
    setBusy(true);
    try {
      await customerFetch(storeSlug, "/api/customer-auth/verify-code/", {
        method: "POST",
        body: JSON.stringify({ phone, code, store_slug: storeSlug }),
      });
      // Server component will re-read the cookie and render the dashboard.
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setError("Too many attempts. Please request a new code.");
        setStep("phone");
        setCode("");
      } else {
        setError("Invalid code. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  const wrapperStyle: React.CSSProperties | undefined = brand.accent
    ? ({ "--pd-accent": brand.accent, "--accent": brand.accent } as React.CSSProperties)
    : undefined;

  return (
    <div className="pd-page pd-page--booking" style={wrapperStyle}>
      <header className="pd-page-head">
        <div className="pd-brand-logo">
          {brand.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="pd-brand-logo-img" src={brand.logo_url} alt={brand.name} />
          ) : (
            <span className="pd-brand-mark" aria-hidden>
              <Icon.logo size={28} />
            </span>
          )}
        </div>
        <div className="pd-eyebrow">My account</div>
        <h1 className="pd-page-title">
          {step === "phone" ? "Sign in with your phone" : "Enter your code"}
        </h1>
        <p className="pd-page-sub">
          {step === "phone"
            ? "We'll text you a 6-digit code to verify your number."
            : `Code sent to ${phone}. It expires in 10 minutes.`}
        </p>
      </header>

      <section className="pd-step is-active">
        <div className="pd-step-body">
          <div className="pd-form">
            {step === "phone" && (
              <>
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
                  />
                </label>
                {error && (
                  <div className="pd-error">
                    <span className="pd-error-dot" />
                    {error}
                  </div>
                )}
                <button
                  className="pd-btn pd-btn--primary pd-btn--lg"
                  disabled={!phone || busy}
                  onClick={requestCode}
                >
                  {busy ? (
                    <>
                      <span className="pd-spinner" /> Sending…
                    </>
                  ) : (
                    <>Send code</>
                  )}
                </button>
              </>
            )}

            {step === "code" && (
              <>
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
                  />
                </label>
                {error && (
                  <div className="pd-error">
                    <span className="pd-error-dot" />
                    {error}
                  </div>
                )}
                <button
                  className="pd-btn pd-btn--primary pd-btn--lg"
                  disabled={code.length !== 6 || busy}
                  onClick={verifyCode}
                >
                  {busy ? (
                    <>
                      <span className="pd-spinner" /> Verifying…
                    </>
                  ) : (
                    <>Verify code</>
                  )}
                </button>
                <button
                  className="pd-btn pd-btn--ghost"
                  disabled={resendIn > 0 || busy}
                  onClick={requestCode}
                >
                  {resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
                </button>
                <button
                  className="pd-btn pd-btn--ghost"
                  disabled={busy}
                  onClick={() => {
                    setStep("phone");
                    setCode("");
                    setError(null);
                  }}
                >
                  Use a different number
                </button>
              </>
            )}
            <p className="pd-fine">
              Your phone is your login. To change it, please ask staff at the front desk.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
