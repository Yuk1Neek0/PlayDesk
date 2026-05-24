"use client";

// Admin → Settings → Payments. Shows the Stripe Connect status for the
// active store and lets the chain owner connect / reconnect their
// account, edit deposit policy, and tweak the refund matrix. Backed
// entirely by /api/admin/stripe/{status,connect,settings} on the v9
// billing app.

import { useCallback, useEffect, useState } from "react";

import { adminFetch } from "@/lib/admin-fetch";
import { useCurrentStore } from "@/lib/store-context";

interface RefundRow {
  min_hours: number;
  refund_pct: number;
}

interface PaymentsStatus {
  store_slug: string;
  account_id: string | null;
  charges_enabled: boolean;
  currency: string;
  deposit_mode: "none" | "percentage" | "fixed";
  deposit_value: string;
  refund_matrix: RefundRow[];
  publishable_key: string;
  configured: boolean;
}

export default function PaymentsSettingsPage() {
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;
  const [data, setData] = useState<PaymentsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [matrixText, setMatrixText] = useState("");

  const load = useCallback(() => {
    adminFetch<PaymentsStatus>("/api/admin/stripe/status/")
      .then((d) => {
        setData(d);
        setMatrixText(JSON.stringify(d.refund_matrix, null, 2));
      })
      .catch(() => setError("Couldn't load payment settings."));
  }, []);

  useEffect(() => {
    setData(null);
    setError(null);
    load();
  }, [load, storeSlug]);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const resp = await adminFetch<{ onboarding_url: string }>(
        "/api/admin/stripe/connect/",
        { method: "POST", body: "{}" },
      );
      if (resp.onboarding_url) {
        window.location.href = resp.onboarding_url;
      }
    } catch {
      setError("Couldn't start Stripe Connect onboarding.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDeposit(mode: "none" | "percentage" | "fixed", value: string) {
    setBusy(true);
    setError(null);
    try {
      await adminFetch("/api/admin/stripe/settings/", {
        method: "PATCH",
        body: JSON.stringify({ deposit_mode: mode, deposit_value: value }),
      });
      load();
    } catch {
      setError("Couldn't save deposit settings.");
    } finally {
      setBusy(false);
    }
  }

  async function saveMatrix() {
    setBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(matrixText);
      await adminFetch("/api/admin/stripe/settings/", {
        method: "PATCH",
        body: JSON.stringify({ refund_matrix: parsed }),
      });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save refund matrix.");
    } finally {
      setBusy(false);
    }
  }

  if (data === null && !error) {
    return <div className="pd-admin"><div className="pd-empty">Loading payment settings…</div></div>;
  }
  if (error && !data) {
    return <div className="pd-admin"><div className="pd-error">{error}</div></div>;
  }
  if (!data) return null;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Settings</div>
          <h1 className="pd-admin-title">Payments</h1>
        </div>
      </header>

      <section className="pd-card" style={{ marginBottom: 16 }}>
        <div className="pd-card-head">
          <h2 className="pd-card-title">Stripe Connect</h2>
          <span className="pd-card-sub">
            {data.charges_enabled
              ? `Connected · ${data.account_id ?? ""}`
              : data.account_id
                ? "Onboarding incomplete"
                : "Not connected"}
          </span>
        </div>
        <div style={{ padding: 12 }}>
          <button
            className="pd-btn pd-btn--primary"
            disabled={busy}
            onClick={connect}
          >
            {data.account_id ? "Reconnect Stripe" : "Connect Stripe"}
          </button>
        </div>
      </section>

      <section className="pd-card" style={{ marginBottom: 16 }}>
        <div className="pd-card-head">
          <h2 className="pd-card-title">Deposit policy</h2>
        </div>
        <DepositForm
          initialMode={data.deposit_mode}
          initialValue={data.deposit_value}
          onSave={saveDeposit}
          busy={busy}
        />
      </section>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">Refund matrix</h2>
          <span className="pd-card-sub">
            JSON array, evaluated top-down. First row whose
            <code> min_hours </code> is met wins.
          </span>
        </div>
        <div style={{ padding: 12, display: "grid", gap: 8 }}>
          <textarea
            className="pd-input"
            value={matrixText}
            onChange={(e) => setMatrixText(e.target.value)}
            rows={6}
            style={{ fontFamily: "monospace", fontSize: 13 }}
          />
          <button className="pd-btn pd-btn--primary" onClick={saveMatrix} disabled={busy}>
            Save refund matrix
          </button>
          {error && <div className="pd-error">{error}</div>}
        </div>
      </section>
    </div>
  );
}

function DepositForm({
  initialMode,
  initialValue,
  onSave,
  busy,
}: {
  initialMode: "none" | "percentage" | "fixed";
  initialValue: string;
  onSave: (mode: "none" | "percentage" | "fixed", value: string) => void;
  busy: boolean;
}) {
  const [mode, setMode] = useState(initialMode);
  const [value, setValue] = useState(initialValue);

  return (
    <div style={{ padding: 12, display: "grid", gap: 8 }}>
      <label className="pd-field">
        <span className="pd-field-label">Mode</span>
        <select
          className="pd-input"
          value={mode}
          onChange={(e) => setMode(e.target.value as typeof mode)}
        >
          <option value="none">None — no deposit required</option>
          <option value="percentage">Percentage of total</option>
          <option value="fixed">Fixed amount</option>
        </select>
      </label>
      <label className="pd-field">
        <span className="pd-field-label">
          {mode === "percentage" ? "Percent (0–100)" : "Amount"}
        </span>
        <input
          className="pd-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={mode === "none"}
        />
      </label>
      <button
        className="pd-btn pd-btn--primary"
        onClick={() => onSave(mode, value)}
        disabled={busy}
      >
        Save deposit policy
      </button>
    </div>
  );
}
