"use client";

// QuoteSandbox — "test this rule" pane on the /admin/pricing page.
// Pick resource + start_at + end_at + optional customer_id → call
// POST /api/quote/ → render the engine's line-item breakdown. Writes
// nothing.

import { useState } from "react";

import { adminFetchQuote, type QuoteResponse, type Resource } from "@/lib/api";

export default function QuoteSandbox({ resources }: { resources: Resource[] }) {
  const [resourceId, setResourceId] = useState<number | null>(
    resources[0]?.id ?? null,
  );
  const today = new Date().toISOString().slice(0, 10);
  const [startAt, setStartAt] = useState<string>(`${today}T20:00`);
  const [endAt, setEndAt] = useState<string>(`${today}T22:00`);
  const [customerId, setCustomerId] = useState<string>("");
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    if (resourceId == null) return;
    setLoading(true);
    setError("");
    try {
      const body: {
        resource_id: number;
        start_at: string;
        end_at: string;
        customer_id?: number;
      } = {
        resource_id: resourceId,
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
      };
      if (customerId.trim()) body.customer_id = Number(customerId.trim());
      const q = await adminFetchQuote(body);
      setQuote(q);
    } catch {
      setError("Couldn't fetch quote — check inputs and try again.");
      setQuote(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="pd-card" style={{ marginTop: 16 }} data-testid="pd-quote-sandbox">
      <div className="pd-card-head">
        <h2 className="pd-card-title">Test this configuration</h2>
        <span className="pd-card-sub">Read-only — nothing saves.</span>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr 1fr auto",
          gap: 10,
          alignItems: "end",
        }}
      >
        <label className="pd-field">
          <span className="pd-field-label">Resource</span>
          <select
            className="pd-input"
            value={resourceId ?? ""}
            onChange={(e) => setResourceId(e.target.value ? Number(e.target.value) : null)}
          >
            {resources.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="pd-field">
          <span className="pd-field-label">Start</span>
          <input
            type="datetime-local"
            className="pd-input"
            value={startAt}
            onChange={(e) => setStartAt(e.target.value)}
          />
        </label>
        <label className="pd-field">
          <span className="pd-field-label">End</span>
          <input
            type="datetime-local"
            className="pd-input"
            value={endAt}
            onChange={(e) => setEndAt(e.target.value)}
          />
        </label>
        <label className="pd-field">
          <span className="pd-field-label">Customer ID (optional)</span>
          <input
            className="pd-input pd-mono"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
          />
        </label>
        <button
          className="pd-btn pd-btn--primary pd-btn--sm"
          onClick={run}
          disabled={loading || resourceId == null}
        >
          {loading ? "…" : "Quote"}
        </button>
      </div>
      {error && (
        <div className="pd-error" style={{ marginTop: 8 }}>
          <span className="pd-error-dot" /> {error}
        </div>
      )}
      {quote && (
        <div className="pd-summary" style={{ marginTop: 12 }}>
          {quote.line_items.map((li, idx) => (
            <div className="pd-summary-row" key={`${li.label}-${idx}`}>
              <span className="pd-summary-key">{li.label}</span>
              <span className="pd-summary-val pd-mono">${li.amount}</span>
            </div>
          ))}
          <div className="pd-summary-row pd-summary-row--total">
            <span className="pd-summary-key">Total</span>
            <span className="pd-summary-val pd-mono">${quote.total_amount}</span>
          </div>
        </div>
      )}
    </section>
  );
}
