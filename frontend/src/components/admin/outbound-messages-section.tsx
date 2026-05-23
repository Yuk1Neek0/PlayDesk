// "Outbound messages" card for the /admin/customers/[id] detail page.
// Lists the last 20 outbound rows (status pill, timestamp, body preview,
// failure-reason on hover) and polls every 30s so a freshly-sent message
// shows up without a manual reload.

"use client";

import { useEffect, useState } from "react";

import { fmtDate, fmtTime, relTime } from "@/components/pd-ui";
import {
  adminListOutboundMessages,
  type OutboundMessage,
  type OutboundStatus,
} from "@/lib/api";

interface Props {
  customerId: number;
}

interface State {
  loading: boolean;
  error: boolean;
  rows: OutboundMessage[];
}

const EMPTY: State = { loading: true, error: false, rows: [] };
const POLL_MS = 30_000;
const BODY_PREVIEW_MAX = 120;

const STATUS_LABEL: Record<OutboundStatus, string> = {
  queued: "Queued",
  sent: "Sent",
  failed: "Failed",
  cancelled: "Cancelled",
};

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1).trimEnd()}…`;
}

export default function OutboundMessagesSection({ customerId }: Props) {
  const [state, setState] = useState<State>(EMPTY);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const rows = await adminListOutboundMessages({ customer_id: customerId, limit: 20 });
        if (!cancelled) setState({ loading: false, error: false, rows });
      } catch {
        if (!cancelled) setState((s) => ({ ...s, loading: false, error: true }));
      }
    }

    void load();
    const handle = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [customerId]);

  return (
    <section className="pd-card">
      <div className="pd-card-head">
        <h2 className="pd-card-title">Outbound messages</h2>
        <span className="pd-card-sub">{state.rows.length}</span>
      </div>

      {state.loading ? (
        <div className="pd-empty">Loading…</div>
      ) : state.error ? (
        <div className="pd-error">
          <span className="pd-error-dot" /> Couldn&apos;t load outbound messages.
        </div>
      ) : state.rows.length === 0 ? (
        <div className="pd-empty">No outbound messages yet.</div>
      ) : (
        <div className="pd-preview-body">
          {state.rows.map((row) => {
            const ts = row.sent_at ?? row.scheduled_for ?? row.created_at;
            const pillClass = `pd-chip pd-chip--ghost pd-outbound-pill pd-outbound-pill--${row.status}`;
            return (
              <div
                key={row.id}
                className="pd-pmsg pd-pmsg--ai"
                style={{ maxWidth: "100%" }}
                title={row.status === "failed" && row.failure_reason ? row.failure_reason : undefined}
              >
                <div className="pd-card-sub pd-mono" style={{ marginBottom: 6 }}>
                  <span className={pillClass}>{STATUS_LABEL[row.status]}</span>
                  {"  "}
                  <span title={new Date(ts).toISOString()}>
                    {relTime(ts)} · {fmtDate(ts)} {fmtTime(ts)}
                  </span>
                  {"  · "}
                  <span>{row.template_key}</span>
                </div>
                <div className="pd-pmsg-text">{truncate(row.body, BODY_PREVIEW_MAX)}</div>
                {row.status === "failed" && row.failure_reason ? (
                  <div className="pd-card-sub" style={{ marginTop: 6, color: "var(--pd-error)" }}>
                    {row.failure_reason}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
