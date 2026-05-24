"use client";

// /admin/rewards — CRUD list for per-store reward catalogue.
// Mirrors the simple table-plus-edit-drawer pattern used elsewhere in the
// admin app (no new CSS).

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  adminCreateReward,
  adminDeleteReward,
  adminListRewards,
  adminUpdateReward,
  listResources,
  type Reward,
} from "@/lib/api";
import { useStaffSession } from "@/lib/staff-session";
import { useCurrentStore } from "@/lib/store-context";

interface DraftReward {
  id: number | null; // null = new
  name: string;
  description: string;
  cost_points: number;
  enabled: boolean;
}

const BLANK_DRAFT: DraftReward = {
  id: null,
  name: "",
  description: "",
  cost_points: 10,
  enabled: true,
};

export default function AdminRewardsPage() {
  const [storeId, setStoreId] = useState<number | null>(null);
  const [rewards, setRewards] = useState<Reward[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [draft, setDraft] = useState<DraftReward | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const { user, ready: authReady } = useStaffSession();
  const router = useRouter();
  useEffect(() => {
    if (authReady && !user?.is_staff) router.replace("/staff/login");
  }, [authReady, user, router]);

  // v6 multi-location: prefer the active store from <StoreProvider>;
  // fall back to first-resource derivation for single-store deployments.
  const { current } = useCurrentStore();
  const currentStoreId = current?.id ?? null;

  useEffect(() => {
    let cancelled = false;
    if (currentStoreId !== null) {
      setStoreId(currentStoreId);
      return () => {
        cancelled = true;
      };
    }
    listResources()
      .then((page) => {
        if (cancelled) return;
        const first = page.results[0];
        if (!first) {
          setError(true);
          setLoading(false);
          return;
        }
        setStoreId(first.store_id);
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [currentStoreId]);

  const refresh = useCallback(async (sid: number) => {
    const list = await adminListRewards(sid);
    setRewards(list);
  }, []);

  useEffect(() => {
    if (storeId === null) return;
    setLoading(true);
    refresh(storeId)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [storeId, refresh]);

  async function submitDraft() {
    if (!draft || storeId === null) return;
    setSaving(true);
    setSaveError("");
    try {
      if (draft.id === null) {
        await adminCreateReward({
          store: storeId,
          name: draft.name.trim(),
          description: draft.description.trim(),
          cost_points: draft.cost_points,
          enabled: draft.enabled,
        });
      } else {
        await adminUpdateReward(draft.id, {
          name: draft.name.trim(),
          description: draft.description.trim(),
          cost_points: draft.cost_points,
          enabled: draft.enabled,
        });
      }
      setDraft(null);
      await refresh(storeId);
    } catch {
      setSaveError("Couldn't save this reward — check fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  async function removeReward(id: number) {
    if (storeId === null) return;
    if (!confirm("Delete this reward? It cannot be undone.")) return;
    try {
      await adminDeleteReward(id);
      await refresh(storeId);
    } catch {
      // refetch to recover state
      await refresh(storeId);
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (!user?.is_staff) return null;
  if (loading) {
    return (
      <div className="pd-admin">
        <div className="pd-empty">Loading rewards…</div>
      </div>
    );
  }
  if (error || storeId === null) {
    return (
      <div className="pd-admin">
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load rewards. Refresh to try again.
        </div>
      </div>
    );
  }

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Memberships</div>
          <h1 className="pd-admin-title">Rewards catalogue</h1>
        </div>
        <div className="pd-admin-head-r">
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            onClick={() => setDraft({ ...BLANK_DRAFT })}
          >
            New reward
          </button>
        </div>
      </header>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">
            {rewards.length} reward{rewards.length === 1 ? "" : "s"}
          </h2>
          <span className="pd-card-sub">Click a row to edit</span>
        </div>
        {rewards.length === 0 ? (
          <div className="pd-empty">No rewards yet. Use “New reward” to add one.</div>
        ) : (
          <div className="pd-table">
            <div
              className="pd-tr pd-tr--head"
              style={{ gridTemplateColumns: "1.4fr 2fr 0.8fr 0.6fr 0.8fr" }}
            >
              <div className="pd-th">Name</div>
              <div className="pd-th">Description</div>
              <div className="pd-th">Cost</div>
              <div className="pd-th">Enabled</div>
              <div className="pd-th">Actions</div>
            </div>
            {rewards.map((r) => (
              <div
                key={r.id}
                className="pd-tr"
                style={{ gridTemplateColumns: "1.4fr 2fr 0.8fr 0.6fr 0.8fr" }}
              >
                <div className="pd-td pd-td-strong">{r.name}</div>
                <div className="pd-td pd-td-sub">{r.description || "—"}</div>
                <div className="pd-td pd-mono">{r.cost_points}</div>
                <div className="pd-td">
                  <span className="pd-chip pd-chip--ghost">
                    {r.enabled ? "On" : "Off"}
                  </span>
                </div>
                <div className="pd-td" style={{ display: "flex", gap: 6 }}>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() =>
                      setDraft({
                        id: r.id,
                        name: r.name,
                        description: r.description,
                        cost_points: r.cost_points,
                        enabled: r.enabled,
                      })
                    }
                  >
                    Edit
                  </button>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => removeReward(r.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {draft && (
        <RewardDrawer
          draft={draft}
          onChange={setDraft}
          onClose={() => setDraft(null)}
          onSave={submitDraft}
          saving={saving}
          error={saveError}
        />
      )}
    </div>
  );
}

function RewardDrawer({
  draft,
  onChange,
  onClose,
  onSave,
  saving,
  error,
}: {
  draft: DraftReward;
  onChange: (d: DraftReward) => void;
  onClose: () => void;
  onSave: () => void;
  saving: boolean;
  error: string;
}) {
  const canSave =
    draft.name.trim().length > 0 && draft.cost_points >= 1 && !saving;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={draft.id === null ? "New reward" : "Edit reward"}
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
        style={{ maxWidth: 520, width: "100%", maxHeight: "85vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pd-card-head">
          <h3 className="pd-card-title">
            {draft.id === null ? "New reward" : "Edit reward"}
          </h3>
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={onClose}
            aria-label="Close"
          >
            Close
          </button>
        </div>
        <div className="pd-field" style={{ marginBottom: 10 }}>
          <span className="pd-field-label">Name</span>
          <input
            className="pd-input"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
          />
        </div>
        <div className="pd-field" style={{ marginBottom: 10 }}>
          <span className="pd-field-label">Description</span>
          <textarea
            className="pd-input"
            rows={3}
            value={draft.description}
            onChange={(e) => onChange({ ...draft, description: e.target.value })}
          />
        </div>
        <div
          className="pd-field"
          style={{ marginBottom: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
        >
          <label className="pd-field">
            <span className="pd-field-label">Cost (points)</span>
            <input
              className="pd-input pd-mono"
              type="number"
              min={1}
              value={draft.cost_points}
              onChange={(e) =>
                onChange({ ...draft, cost_points: Math.max(1, Number(e.target.value || 1)) })
              }
            />
          </label>
          <label
            className="pd-chip pd-chip--ghost"
            style={{ cursor: "pointer", alignSelf: "end" }}
          >
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => onChange({ ...draft, enabled: e.target.checked })}
              style={{ marginRight: 6 }}
            />
            Enabled
          </label>
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
            onClick={onSave}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
