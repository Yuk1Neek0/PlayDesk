"use client";

// Admin → Payments ledger. Paginated table of Payment rows for the
// active store. Filters: kind + status. Backed by /api/admin/payments/.

import { useEffect, useState } from "react";

import { adminFetch } from "@/lib/admin-fetch";
import { useCurrentStore } from "@/lib/store-context";

interface PaymentRow {
  id: number;
  created_at: string;
  booking_id: number;
  customer_name: string;
  kind: "deposit" | "balance" | "refund" | "adjustment";
  amount: string;
  currency: string;
  status: "pending" | "succeeded" | "failed" | "refunded";
  stripe_charge_id: string;
  stripe_payment_intent_id: string;
}

interface PaymentsResponse {
  count: number;
  results: PaymentRow[];
}

export default function PaymentsLedgerPage() {
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;
  const [rows, setRows] = useState<PaymentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"all" | PaymentRow["kind"]>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | PaymentRow["status"]>(
    "all",
  );

  useEffect(() => {
    const params = new URLSearchParams();
    if (kind !== "all") params.set("kind", kind);
    if (statusFilter !== "all") params.set("status", statusFilter);
    const qs = params.toString();
    setError(null);
    adminFetch<PaymentsResponse>(`/api/admin/payments/${qs ? `?${qs}` : ""}`)
      .then((d) => setRows(d.results))
      .catch(() => setError("Couldn't load payments."));
  }, [storeSlug, kind, statusFilter]);

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Finance</div>
          <h1 className="pd-admin-title">Payments</h1>
        </div>
      </header>

      <div className="pd-filters" style={{ marginBottom: 12 }}>
        <FilterChips
          label="Kind"
          value={kind}
          onChange={(v) => setKind(v as typeof kind)}
          options={[
            ["all", "All"],
            ["deposit", "Deposit"],
            ["balance", "Balance"],
            ["refund", "Refund"],
            ["adjustment", "Adjustment"],
          ]}
        />
        <FilterChips
          label="Status"
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as typeof statusFilter)}
          options={[
            ["all", "All"],
            ["pending", "Pending"],
            ["succeeded", "Succeeded"],
            ["failed", "Failed"],
            ["refunded", "Refunded"],
          ]}
        />
      </div>

      {error && <div className="pd-error">{error}</div>}

      <section className="pd-card">
        <div className="pd-table">
          <div className="pd-tr pd-tr--head">
            <div className="pd-th">When</div>
            <div className="pd-th">Booking</div>
            <div className="pd-th">Customer</div>
            <div className="pd-th">Kind</div>
            <div className="pd-th">Amount</div>
            <div className="pd-th">Status</div>
            <div className="pd-th">Charge ID</div>
          </div>
          {rows.length === 0 && (
            <div className="pd-table-empty">No payments match these filters.</div>
          )}
          {rows.map((p) => (
            <div key={p.id} className="pd-tr">
              <div className="pd-td pd-td-sub">
                {new Date(p.created_at).toLocaleString()}
              </div>
              <div className="pd-td pd-mono">#{p.booking_id}</div>
              <div className="pd-td">{p.customer_name}</div>
              <div className="pd-td">
                <span className="pd-chip pd-chip--ghost">{p.kind}</span>
              </div>
              <div className="pd-td pd-mono">
                {p.currency} {p.amount}
              </div>
              <div className="pd-td">{p.status}</div>
              <div className="pd-td pd-mono pd-td-sub">
                {p.stripe_charge_id ? p.stripe_charge_id.slice(0, 12) : "—"}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function FilterChips({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <div className="pd-filter">
      <span className="pd-filter-label">{label}</span>
      <div className="pd-seg pd-seg--sm">
        {options.map(([k, l]) => (
          <button
            key={k}
            className={`pd-seg-item ${value === k ? "is-active" : ""}`}
            onClick={() => onChange(k)}
          >
            {l}
          </button>
        ))}
      </div>
    </div>
  );
}
