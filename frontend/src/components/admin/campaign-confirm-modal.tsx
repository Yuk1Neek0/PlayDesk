"use client";

// Send-confirmation modal — the last thing standing between a curious
// click and 1000 SMSes.
//
// The "Send" button is only enabled when count > 0, body is non-empty,
// and the confirm checkbox is ticked. Body is previewed against the
// first sample customer via `safeFormat` (mirrors the backend's
// SafeFormatter — unknown keys render as `{unknown}` so staff spot them
// before pulling the trigger).

import { useMemo, useState } from "react";

import { safeFormat, type SafeFormatContext } from "@/lib/safeFormat";
import type { SegmentPreviewCustomer } from "@/lib/api";

interface Props {
  segmentName: string;
  body: string;
  count: number;
  sample: SegmentPreviewCustomer | null;
  storeName: string;
  scheduledFor: string | null;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
  submitting: boolean;
  submitError: string | null;
}

export function CampaignConfirmModal({
  segmentName,
  body,
  count,
  sample,
  storeName,
  scheduledFor,
  onCancel,
  onConfirm,
  submitting,
  submitError,
}: Props) {
  const [checked, setChecked] = useState(false);

  const previewCtx: SafeFormatContext = useMemo(
    () => ({
      customer: sample ?? { name: "(no recipient)", phone: "", tags: [] },
      store: { name: storeName },
    }),
    [sample, storeName],
  );
  const renderedBody = useMemo(() => safeFormat(body, previewCtx), [body, previewCtx]);

  const trimmedBody = body.trim().length > 0;
  const canSend = count > 0 && trimmedBody && checked && !submitting;

  return (
    <div className="pd-modal-overlay" role="dialog" aria-modal="true">
      <div className="pd-modal">
        <div className="pd-card-head">
          <h2 className="pd-card-title">Send campaign</h2>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <div>
            <span className="pd-card-sub">Recipients</span>
            <div className="pd-td-strong">
              {count} customer{count === 1 ? "" : "s"} in &ldquo;{segmentName}&rdquo;
            </div>
            {count === 0 && (
              <div className="pd-error" style={{ marginTop: 8 }}>
                <span className="pd-error-dot" />
                This segment matches no one right now. Send is disabled.
              </div>
            )}
          </div>

          <div>
            <span className="pd-card-sub">Schedule</span>
            <div className="pd-mono">{scheduledFor ?? "Send now"}</div>
          </div>

          <div>
            <span className="pd-card-sub">
              Preview {sample ? `(rendered against ${sample.name || sample.phone})` : ""}
            </span>
            <div
              className="pd-card"
              style={{
                padding: 12,
                marginTop: 4,
                whiteSpace: "pre-wrap",
                fontFamily: "var(--font-mono, ui-monospace)",
                fontSize: 13,
              }}
            >
              {renderedBody || <em>(empty body)</em>}
            </div>
          </div>

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              cursor: count > 0 && trimmedBody ? "pointer" : "not-allowed",
            }}
          >
            <input
              type="checkbox"
              checked={checked}
              disabled={count === 0 || !trimmedBody || submitting}
              onChange={(e) => setChecked(e.target.checked)}
            />
            <span>
              I understand this will send {count} SMS message{count === 1 ? "" : "s"} immediately.
            </span>
          </label>

          {submitError && (
            <div className="pd-error">
              <span className="pd-error-dot" />
              {submitError}
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            disabled={!canSend}
            onClick={() => {
              void onConfirm();
            }}
          >
            {submitting ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
