"use client";

// /admin/tiers — CRUD list for per-store reward tiers.
// Same table-plus-drawer pattern as /admin/rewards.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  adminCreateTier,
  adminDeleteTier,
  adminListTiers,
  adminUpdateTier,
  listResources,
  type RewardTier,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface DraftTier {
  id: number | null;
  name: string;
  min_lifetime_points: number;
  perks_text: string;
  position: number;
}

const BLANK_DRAFT: DraftTier = {
  id: null,
  name: "",
  min_lifetime_points: 0,
  perks_text: "",
  position: 0,
};

export default function AdminTiersPage() {
  const [storeId, setStoreId] = useState<number | null>(null);
  const [tiers, setTiers] = useState<RewardTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [draft, setDraft] = useState<DraftTier | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const { user, ready: authReady } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

  useEffect(() => {
    let cancelled = false;
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
  }, []);

  const refresh = useCallback(async (sid: number) => {
    const list = await adminListTiers(sid);
    setTiers(list);
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
        await adminCreateTier({
          store: storeId,
          name: draft.name.trim(),
          min_lifetime_points: draft.min_lifetime_points,
          perks_text: draft.perks_text.trim(),
          position: draft.position,
        });
      } else {
        await adminUpdateTier(draft.id, {
          name: draft.name.trim(),
          min_lifetime_points: draft.min_lifetime_points,
          perks_text: draft.perks_text.trim(),
          position: draft.position,
        });
      }
      setDraft(null);
      await refresh(storeId);
    } catch {
      setSaveError(
        "Couldn't save this tier — positions must be unique per store.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function removeTier(id: number) {
    if (storeId === null) return;
    if (!confirm("Delete this tier? It cannot be undone.")) return;
    try {
      await adminDeleteTier(id);
      await refresh(storeId);
    } catch {
      await refresh(storeId);
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;
  if (loading) {
    return (
      <div className="pd-admin">
        <div className="pd-empty">Loading tiers…</div>
      </div>
    );
  }
  if (error || storeId === null) {
    return (
      <div className="pd-admin">
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load tiers. Refresh to try again.
        </div>
      </div>
    );
  }

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Memberships</div>
          <h1 className="pd-admin-title">Reward tiers</h1>
        </div>
        <div className="pd-admin-head-r">
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            onClick={() =>
              setDraft({ ...BLANK_DRAFT, position: tiers.length })
            }
          >
            New tier
          </button>
        </div>
      </header>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">
            {tiers.length} tier{tiers.length === 1 ? "" : "s"}
          </h2>
          <span className="pd-card-sub">Ordered by position</span>
        </div>
        {tiers.length === 0 ? (
          <div className="pd-empty">
            No tiers yet. Use “New tier” to add the first one.
          </div>
        ) : (
          <div className="pd-table">
            <div
              className="pd-tr pd-tr--head"
              style={{ gridTemplateColumns: "0.6fr 1.2fr 1fr 2fr 0.8fr" }}
            >
              <div className="pd-th">Position</div>
              <div className="pd-th">Name</div>
              <div className="pd-th">Min lifetime pts</div>
              <div className="pd-th">Perks</div>
              <div className="pd-th">Actions</div>
            </div>
            {tiers.map((t) => (
              <div
                key={t.id}
                className="pd-tr"
                style={{ gridTemplateColumns: "0.6fr 1.2fr 1fr 2fr 0.8fr" }}
              >
                <div className="pd-td pd-mono">{t.position}</div>
                <div className="pd-td pd-td-strong">{t.name}</div>
                <div className="pd-td pd-mono">{t.min_lifetime_points}</div>
                <div className="pd-td pd-td-sub">{t.perks_text || "—"}</div>
                <div className="pd-td" style={{ display: "flex", gap: 6 }}>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() =>
                      setDraft({
                        id: t.id,
                        name: t.name,
                        min_lifetime_points: t.min_lifetime_points,
                        perks_text: t.perks_text,
                        position: t.position,
                      })
                    }
                  >
                    Edit
                  </button>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => removeTier(t.id)}
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
        <TierDrawer
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

function TierDrawer({
  draft,
  onChange,
  onClose,
  onSave,
  saving,
  error,
}: {
  draft: DraftTier;
  onChange: (d: DraftTier) => void;
  onClose: () => void;
  onSave: () => void;
  saving: boolean;
  error: string;
}) {
  const canSave = draft.name.trim().length > 0 && !saving;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={draft.id === null ? "New tier" : "Edit tier"}
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
            {draft.id === null ? "New tier" : "Edit tier"}
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
        <div
          className="pd-field"
          style={{ marginBottom: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
        >
          <label className="pd-field">
            <span className="pd-field-label">Min lifetime points</span>
            <input
              className="pd-input pd-mono"
              type="number"
              min={0}
              value={draft.min_lifetime_points}
              onChange={(e) =>
                onChange({
                  ...draft,
                  min_lifetime_points: Math.max(0, Number(e.target.value || 0)),
                })
              }
            />
          </label>
          <label className="pd-field">
            <span className="pd-field-label">Position</span>
            <input
              className="pd-input pd-mono"
              type="number"
              min={0}
              value={draft.position}
              onChange={(e) =>
                onChange({ ...draft, position: Math.max(0, Number(e.target.value || 0)) })
              }
            />
          </label>
        </div>
        <div className="pd-field" style={{ marginBottom: 10 }}>
          <span className="pd-field-label">Perks</span>
          <textarea
            className="pd-input"
            rows={3}
            placeholder="Free coffee, priority booking, …"
            value={draft.perks_text}
            onChange={(e) => onChange({ ...draft, perks_text: e.target.value })}
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
            onClick={onSave}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
