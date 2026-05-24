"use client";

// /staff/login/ form — client component.
//
// Submits {username, password} to POST /api/staff/login/. The backend
// sets the Django session cookie on success; we then push to `next`
// (defaults to /admin) and let <StaffSessionProvider> re-validate via
// /api/staff/me/ when the admin layout mounts.
//
// Phase 2 commit 4: ported from raw Tailwind to the pd-* design system so
// the staff path matches the customer surfaces visually (DESIGN_AUDIT.md
// §1b — "staff login is a different product").

import { useState } from "react";

import { Icon } from "@/components/pd-ui";

interface LoginFormProps {
  /** URL to land on after a successful login. */
  next: string;
}

type Status = "idle" | "submitting" | "error";

export default function LoginForm({ next }: LoginFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("submitting");
    setErrorMsg("");
    try {
      const resp = await fetch("/api/staff/login/", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (resp.status === 200) {
        // Hard navigation so the server-rendered admin layout picks up
        // the freshly-minted sessionid cookie cleanly.
        window.location.assign(next);
        return;
      }
      let detail: string;
      if (resp.status === 401) detail = "Invalid credentials.";
      else if (resp.status === 403) detail = "This account isn't a staff account.";
      else if (resp.status === 429)
        detail = "Too many attempts. Try again in a few minutes.";
      else detail = `Sign-in failed (${resp.status}).`;
      setErrorMsg(detail);
      setStatus("error");
    } catch {
      setErrorMsg("Network error. Please try again.");
      setStatus("error");
    }
  }

  const submitting = status === "submitting";

  return (
    <div className="pd-page pd-page--booking">
      <header className="pd-page-head">
        <div className="pd-brand-logo">
          <span className="pd-brand-mark" aria-hidden>
            <Icon.logo size={28} />
          </span>
        </div>
        <div className="pd-eyebrow">Staff only</div>
        <h1 className="pd-page-title">Staff sign-in</h1>
        <p className="pd-page-sub">
          Sign in with your PlayDesk staff account to open the admin
          dashboard.
        </p>
      </header>

      <section className="pd-step is-active" style={{ maxWidth: 460 }}>
        <div className="pd-step-body">
          <form onSubmit={handleSubmit} className="pd-form">
            <label className="pd-field" htmlFor="username">
              <span className="pd-field-label">Username</span>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                required
                className="pd-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={submitting}
              />
            </label>

            <label className="pd-field" htmlFor="password">
              <span className="pd-field-label">Password</span>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className="pd-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
              />
            </label>

            {status === "error" && errorMsg && (
              <div className="pd-error" role="alert">
                <span className="pd-error-dot" />
                {errorMsg}
              </div>
            )}

            <button
              type="submit"
              className="pd-btn pd-btn--primary pd-btn--lg"
              disabled={submitting || !username || !password}
            >
              {submitting ? (
                <>
                  <span className="pd-spinner" /> Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </button>

            <p className="pd-fine">
              Forgot your password? Contact your administrator.
            </p>
          </form>
        </div>
      </section>
    </div>
  );
}
