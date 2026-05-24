"use client";

// Admin → Settings → Door QR (rotating check-in, v11a).
//
// Shows the current rotating key for the active store, lets staff
// edit the rotation period, manually rotate now, and pop the
// fullscreen lobby display in a new tab.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { adminFetch } from "@/lib/admin-fetch";
import { useCurrentStore } from "@/lib/store-context";

interface ActiveKey {
  key: string;
  created_at: string;
  expires_at: string;
  rotation_minutes: number;
  qr_url: string;
}

function maskKey(key: string): string {
  if (key.length <= 4) return "•••";
  return `${key.slice(0, 2)}${"•".repeat(key.length - 4)}${key.slice(-2)}`;
}

function secondsUntil(iso: string): number {
  const end = new Date(iso).getTime();
  return Math.max(0, Math.round((end - Date.now()) / 1000));
}

export default function CheckinSettingsPage() {
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;
  const [data, setData] = useState<ActiveKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [draftMinutes, setDraftMinutes] = useState<number | "">("");
  const [countdown, setCountdown] = useState(0);

  const load = useCallback(() => {
    adminFetch<ActiveKey>("/api/admin/checkin/active-key/")
      .then((d) => {
        setData(d);
        setDraftMinutes(d.rotation_minutes);
      })
      .catch(() => setError("Couldn't load the rotating key."));
  }, []);

  useEffect(() => {
    setData(null);
    setError(null);
    setReveal(false);
    load();
  }, [load, storeSlug]);

  // Refresh the key every 30s so the page never shows a stale row.
  useEffect(() => {
    const t = window.setInterval(load, 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  // Countdown ticker — recompute every second from data.expires_at.
  useEffect(() => {
    if (data === null) return;
    setCountdown(secondsUntil(data.expires_at));
    const t = window.setInterval(() => setCountdown(secondsUntil(data.expires_at)), 1000);
    return () => window.clearInterval(t);
  }, [data]);

  async function rotateNow() {
    if (busy) return;
    if (!window.confirm("Rotate the door QR now? Any displayed copies will need a refresh.")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await adminFetch<ActiveKey>("/api/admin/checkin/rotate/", {
        method: "POST",
        body: "{}",
      });
      setData(next);
      setReveal(false);
    } catch {
      setError("Couldn't rotate. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings() {
    if (busy || draftMinutes === "" || draftMinutes < 1 || draftMinutes > 60) return;
    setBusy(true);
    setError(null);
    try {
      const next = await adminFetch<ActiveKey>("/api/admin/checkin/settings/", {
        method: "PATCH",
        body: JSON.stringify({ rotation_minutes: draftMinutes }),
      });
      setData(next);
    } catch {
      setError("Couldn't save settings.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="pd-admin" data-testid="checkin-settings-page">
      <header className="pd-section-head">
        <h1>Door QR — check-in code</h1>
        <p className="pd-page-sub">
          Customers scan this QR at the door, enter their phone + OTP, and
          check in for their booking.
        </p>
      </header>

      {error && (
        <div className="pd-error" data-testid="checkin-settings-error">
          <span className="pd-error-dot" /> {error}
        </div>
      )}

      {data === null ? (
        <div className="pd-empty">Loading…</div>
      ) : (
        <>
          <section className="pd-card">
            <h2>Current key</h2>
            <div data-testid="active-key" className="pd-mono">
              {reveal ? data.key : maskKey(data.key)}
            </div>
            <button
              type="button"
              className="pd-btn pd-btn--ghost pd-btn--sm"
              onClick={() => setReveal((r) => !r)}
              data-testid="reveal-toggle"
            >
              {reveal ? "Hide" : "Reveal"}
            </button>
            <dl className="pd-meta">
              <dt>Created</dt>
              <dd>{new Date(data.created_at).toLocaleString()}</dd>
              <dt>Expires</dt>
              <dd>{new Date(data.expires_at).toLocaleString()}</dd>
              <dt>Time left</dt>
              <dd data-testid="countdown">
                {Math.floor(countdown / 60)}m {countdown % 60}s
              </dd>
            </dl>
          </section>

          <section className="pd-card">
            <h2>Rotation interval</h2>
            <label className="pd-field">
              <span className="pd-field-label">Minutes between rotations (1–60)</span>
              <input
                type="number"
                min={1}
                max={60}
                className="pd-input"
                value={draftMinutes}
                onChange={(e) =>
                  setDraftMinutes(e.target.value === "" ? "" : Number(e.target.value))
                }
                data-testid="rotation-minutes-input"
              />
            </label>
            <button
              type="button"
              className="pd-btn pd-btn--primary"
              disabled={
                busy ||
                draftMinutes === "" ||
                draftMinutes < 1 ||
                draftMinutes > 60 ||
                draftMinutes === data.rotation_minutes
              }
              onClick={saveSettings}
              data-testid="save-settings"
            >
              Save
            </button>
          </section>

          <section className="pd-card">
            <h2>Actions</h2>
            <button
              type="button"
              className="pd-btn pd-btn--primary"
              disabled={busy}
              onClick={rotateNow}
              data-testid="rotate-now"
            >
              Rotate now
            </button>
            <Link
              href="/admin/settings/checkin/display"
              className="pd-btn pd-btn--ghost"
              target="_blank"
              data-testid="open-display"
            >
              Open fullscreen display
            </Link>
          </section>
        </>
      )}
    </main>
  );
}
