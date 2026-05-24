"use client";

// MembershipSection — rendered on /admin/customers/[id] below the visit
// history. One composite fetch hydrates the entire card; the adjust /
// redeem modals re-fetch on success.
//
// Modals are simple overlays rendered inline — there is no dedicated
// `pd-modal` token in the design system yet, so we use a fixed-position
// scrim around a pd-card. Animation is skipped per task #111's
// prefers-reduced-motion requirement.

import { useCallback, useEffect, useState } from "react";

import { fmtDate, fmtTime, relTime } from "@/components/pd-ui";
import {
  adminAdjustPoints,
  adminGetMembership,
  adminRedeemReward,
  ApiError,
  type MembershipPayload,
  type PointSource,
  type PointTransaction,
} from "@/lib/api";
import { useCurrentStore } from "@/lib/store-context";

const SOURCE_LABEL: Record<PointSource, string> = {
  booking: "Booking",
  qr_click: "QR click",
  redemption: "Redemption",
  adjustment: "Adjustment",
  backfill: "Backfill",
};

interface Props {
  customerId: number;
}

export default function MembershipSection({ customerId }: Props) {
  const [data, setData] = useState<MembershipPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showAdjust, setShowAdjust] = useState(false);
  const [showRedeem, setShowRedeem] = useState(false);

  // v6 multi-location: refetch on store switch — same rationale as
  // OutboundMessagesSection.
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const payload = await adminGetMembership(customerId);
      setData(payload);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
    // storeSlug included so a store switch triggers refetch with the new scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, storeSlug]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading && !data) {
    return (
      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">Membership</h2>
        </div>
        <div className="pd-empty">Loading membership…</div>
      </section>
    );
  }
  if (error || !data) {
    return (
      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">Membership</h2>
        </div>
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load membership for this customer.
        </div>
      </section>
    );
  }

  return (
    <section className="pd-card">
      <div className="pd-card-head">
        <h2 className="pd-card-title">Membership</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={() => setShowAdjust(true)}
          >
            Adjust
          </button>
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            onClick={() => setShowRedeem(true)}
            disabled={data.available_rewards.length === 0}
            title={
              data.available_rewards.length === 0
                ? "No rewards in budget yet"
                : "Redeem a reward"
            }
          >
            Redeem
          </button>
        </div>
      </div>

      {/* Headline balance + tier */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginBottom: 18,
        }}
      >
        <div className="pd-stat">
          <div className="pd-stat-label">Current balance</div>
          <div className="pd-stat-value pd-mono">{data.balance.toLocaleString()}</div>
          <div className="pd-stat-delta">
            Lifetime {data.lifetime_earned.toLocaleString()} pts
          </div>
        </div>
        <div className="pd-stat">
          <div className="pd-stat-label">Tier</div>
          {data.tier ? (
            <>
              <div className="pd-stat-value">{data.tier.name}</div>
              <div className="pd-stat-delta">
                {data.tier.perks_text || "—"}
              </div>
            </>
          ) : (
            <>
              <div className="pd-stat-value pd-card-sub" style={{ fontSize: 18 }}>
                No tier yet
              </div>
              <div className="pd-stat-delta">
                {data.next_tier && data.points_to_next_tier !== null
                  ? `${data.points_to_next_tier.toLocaleString()} pts to ${data.next_tier.name}`
                  : "No tiers configured"}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Ledger */}
      <RecentTransactions rows={data.recent_transactions} />

      {showAdjust && (
        <AdjustPointsModal
          customerId={customerId}
          onClose={() => setShowAdjust(false)}
          onSuccess={async () => {
            setShowAdjust(false);
            await refresh();
          }}
        />
      )}
      {showRedeem && (
        <RedeemModal
          customerId={customerId}
          balance={data.balance}
          rewards={data.available_rewards}
          onClose={() => setShowRedeem(false)}
          onSuccess={async () => {
            setShowRedeem(false);
            await refresh();
          }}
        />
      )}
    </section>
  );
}

function RecentTransactions({ rows }: { rows: PointTransaction[] }) {
  if (rows.length === 0) {
    return <div className="pd-empty">No ledger activity yet.</div>;
  }
  return (
    <div className="pd-table">
      <div
        className="pd-tr pd-tr--head"
        style={{ gridTemplateColumns: "1.2fr 0.7fr 0.8fr 1.3fr" }}
      >
        <div className="pd-th">When</div>
        <div className="pd-th">Delta</div>
        <div className="pd-th">Source</div>
        <div className="pd-th">Reference</div>
      </div>
      {rows.map((r) => (
        <div
          key={r.id}
          className="pd-tr"
          style={{ gridTemplateColumns: "1.2fr 0.7fr 0.8fr 1.3fr" }}
        >
          <div className="pd-td">
            <div className="pd-td-strong">{fmtDate(r.created_at)}</div>
            <div className="pd-td-sub pd-mono">{fmtTime(r.created_at)}</div>
          </div>
          <div className="pd-td pd-mono pd-td-strong">
            {r.delta > 0 ? `+${r.delta}` : r.delta}
          </div>
          <div className="pd-td">
            <span className="pd-chip pd-chip--ghost">{SOURCE_LABEL[r.source]}</span>
          </div>
          <div className="pd-td pd-td-sub">
            {r.reference || "—"}
            <div className="pd-td-sub pd-mono">
              {r.author_username ? `by ${r.author_username}` : relTime(r.created_at)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────

function ModalShell({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  // Inline styles so this self-contained modal needs no new CSS file.
  // prefers-reduced-motion is honoured by skipping the slide-in animation
  // entirely — there is no transform here.
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        zIndex: 50,
      }}
      onClick={onClose}
    >
      <div
        className="pd-card"
        style={{ maxWidth: 480, width: "100%", maxHeight: "85vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pd-card-head">
          <h3 className="pd-card-title">{title}</h3>
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={onClose}
            aria-label="Close"
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function AdjustPointsModal({
  customerId,
  onClose,
  onSuccess,
}: {
  customerId: number;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [delta, setDelta] = useState<number>(0);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const canSave = delta !== 0 && reason.trim().length > 0 && !saving;

  async function submit() {
    if (!canSave) return;
    setSaving(true);
    setError("");
    try {
      await adminAdjustPoints(customerId, { delta, reason: reason.trim() });
      onSuccess();
    } catch (e) {
      const msg =
        e instanceof ApiError && typeof e.body === "object" && e.body
          ? JSON.stringify(e.body)
          : "Couldn't save the adjustment.";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title="Adjust points" onClose={onClose}>
      <div className="pd-field" style={{ marginBottom: 12 }}>
        <span className="pd-field-label">Delta (positive = credit, negative = debit)</span>
        <input
          className="pd-input pd-mono"
          type="number"
          value={delta}
          onChange={(e) => setDelta(Number(e.target.value || 0))}
        />
      </div>
      <div className="pd-field" style={{ marginBottom: 12 }}>
        <span className="pd-field-label">Reason (required)</span>
        <textarea
          className="pd-input"
          rows={3}
          placeholder="Birthday bonus, manual correction, …"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
      {error && (
        <div className="pd-error" style={{ marginBottom: 10 }}>
          <span className="pd-error-dot" /> {error}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={onClose}>
          Cancel
        </button>
        <button
          className="pd-btn pd-btn--primary pd-btn--sm"
          disabled={!canSave}
          onClick={submit}
        >
          {saving ? "Saving…" : "Save adjustment"}
        </button>
      </div>
    </ModalShell>
  );
}

function RedeemModal({
  customerId,
  balance,
  rewards,
  onClose,
  onSuccess,
}: {
  customerId: number;
  balance: number;
  rewards: MembershipPayload["available_rewards"];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(
    rewards[0]?.id ?? null,
  );
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const selected = rewards.find((r) => r.id === selectedId) ?? null;

  async function submit() {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await adminRedeemReward(customerId, selected.id);
      onSuccess();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const body = (e.body ?? {}) as { balance?: number; cost?: number };
        setError(
          `Not enough points — balance ${body.balance ?? "?"}, costs ${body.cost ?? "?"}.`,
        );
      } else {
        setError("Couldn't redeem this reward. Try again.");
      }
      setConfirming(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title="Redeem a reward" onClose={onClose}>
      <div className="pd-card-sub" style={{ marginBottom: 12 }}>
        Balance: <span className="pd-mono">{balance.toLocaleString()}</span> pts
      </div>
      {rewards.length === 0 ? (
        <div className="pd-empty">No rewards in budget.</div>
      ) : (
        <>
          <div className="pd-field" style={{ marginBottom: 12 }}>
            <span className="pd-field-label">Reward</span>
            <select
              className="pd-input"
              value={selectedId ?? ""}
              onChange={(e) => {
                setSelectedId(Number(e.target.value));
                setConfirming(false);
              }}
            >
              {rewards.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {r.cost_points} pts
                </option>
              ))}
            </select>
          </div>
          {selected?.description && (
            <div className="pd-card-sub" style={{ marginBottom: 12 }}>
              {selected.description}
            </div>
          )}
          {error && (
            <div className="pd-error" style={{ marginBottom: 10 }}>
              <span className="pd-error-dot" /> {error}
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={onClose}>
              Cancel
            </button>
            {!confirming ? (
              <button
                className="pd-btn pd-btn--primary pd-btn--sm"
                disabled={!selected || saving}
                onClick={() => setConfirming(true)}
              >
                Redeem…
              </button>
            ) : (
              <button
                className="pd-btn pd-btn--primary pd-btn--sm"
                disabled={!selected || saving}
                onClick={submit}
              >
                {saving
                  ? "Redeeming…"
                  : `Confirm — debit ${selected?.cost_points ?? 0} pts`}
              </button>
            )}
          </div>
        </>
      )}
    </ModalShell>
  );
}
