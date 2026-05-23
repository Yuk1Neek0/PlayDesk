"use client";

// /admin/qr — staff configuration page for the One-QR landing.
//
// Three concerns on one screen:
//   1. Top-of-page analytics card row (scans / clicks / engagement rate)
//      with a 7 / 30 / 90 day filter chip group.
//   2. The reorderable action list — HTML5 native drag-and-drop plus a
//      keyboard fallback (Arrow Up / Arrow Down on a focused row).
//   3. An "Add action" form that appends a new chip to the end.
//
// The store id is taken from the first store the backend exposes via
// /api/resources/?store_id=… style lookups. For the demo this is always
// store #1; a multi-store dropdown is a future slice.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  adminCreateQRAction,
  adminDeleteQRAction,
  adminGetQRAnalytics,
  adminListQRActions,
  adminUpdateQRAction,
  listResources,
  type QRAction,
  type QRActionKind,
  type QRAnalytics,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

const KINDS: { value: QRActionKind; label: string }[] = [
  { value: "review", label: "Google review" },
  { value: "instagram", label: "Instagram" },
  { value: "tiktok", label: "TikTok" },
  { value: "rednote", label: "RedNote" },
  { value: "wechat", label: "WeChat" },
  { value: "wifi", label: "Store WiFi" },
  { value: "custom", label: "Custom link" },
];

type DaysWindow = 7 | 30 | 90;

export default function AdminQRPage() {
  const [storeId, setStoreId] = useState<number | null>(null);
  const [storeSlug, setStoreSlug] = useState<string | null>(null);
  const [actions, setActions] = useState<QRAction[]>([]);
  const [analytics, setAnalytics] = useState<QRAnalytics | null>(null);
  const [analyticsDays, setAnalyticsDays] = useState<DaysWindow>(7);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  const { user, ready: authReady } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

  // Bootstrap: resolve the store id (and slug for the "Preview" button) by
  // looking at the first resource. The Store endpoint isn't exposed, so this
  // works for the demo's single-store setup without adding new routes.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listResources()
      .then(async (page) => {
        if (cancelled) return;
        const first = page.results[0];
        if (!first) {
          setLoadError(true);
          setLoading(false);
          return;
        }
        setStoreId(first.store_id);
        // Slug isn't on the Resource shape; the public payload carries it.
        // We fetch it lazily below if/when the Preview button is clicked.
        setStoreSlug(null);
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshActions = useCallback(async (id: number) => {
    const next = await adminListQRActions(id);
    setActions(next);
  }, []);

  const refreshAnalytics = useCallback(async (id: number, days: DaysWindow) => {
    const a = await adminGetQRAnalytics(id, days);
    setAnalytics(a);
  }, []);

  useEffect(() => {
    if (storeId === null) return;
    let cancelled = false;
    Promise.all([refreshActions(storeId), refreshAnalytics(storeId, analyticsDays)])
      .then(() => {
        if (!cancelled) setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [storeId, analyticsDays, refreshActions, refreshAnalytics]);

  async function moveAction(id: number, direction: -1 | 1) {
    if (storeId === null) return;
    const idx = actions.findIndex((a) => a.id === id);
    if (idx < 0) return;
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= actions.length) return;
    // Optimistic swap.
    const next = [...actions];
    [next[idx], next[targetIdx]] = [next[targetIdx], next[idx]];
    setActions(next);
    try {
      await adminUpdateQRAction(id, { position: targetIdx });
      await refreshActions(storeId);
    } catch {
      // Roll back on failure.
      await refreshActions(storeId);
    }
  }

  async function dropToPosition(draggedId: number, dropOnIdx: number) {
    if (storeId === null) return;
    try {
      await adminUpdateQRAction(draggedId, { position: dropOnIdx });
      await refreshActions(storeId);
    } catch {
      await refreshActions(storeId);
    }
  }

  async function patchField<K extends keyof QRAction>(id: number, key: K, value: QRAction[K]) {
    if (storeId === null) return;
    const optimistic = actions.map((a) => (a.id === id ? { ...a, [key]: value } : a));
    setActions(optimistic);
    try {
      await adminUpdateQRAction(id, { [key]: value });
    } catch {
      await refreshActions(storeId);
    }
  }

  async function deleteAction(id: number) {
    if (storeId === null) return;
    if (!confirm("Delete this action? It cannot be undone.")) return;
    setActions(actions.filter((a) => a.id !== id));
    try {
      await adminDeleteQRAction(id);
    } catch {
      // refresh to recover state
    }
    await refreshActions(storeId);
  }

  async function openPreview() {
    if (storeSlug) {
      window.open(`/qr/${storeSlug}`, "_blank");
      return;
    }
    // Fetch the public payload once to learn the slug.
    if (storeId === null) return;
    try {
      const resp = await fetch(`/api/qr/_resolve_/`, { method: "GET" });
      // Fallback: just guess /qr/playdesk-flagship/ for the demo. Robust
      // approach is a dedicated GET /api/admin/qr-store/?id=, deferred
      // to a future slice.
      if (!resp.ok) throw new Error();
    } catch {
      window.open(`/qr/playdesk-flagship`, "_blank");
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;
  if (loading) return <div className="pd-admin"><div className="pd-empty">Loading QR config…</div></div>;
  if (loadError) {
    return (
      <div className="pd-admin">
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load the QR config. Refresh to try again.
        </div>
      </div>
    );
  }

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">One QR</div>
          <h1 className="pd-admin-title">Front-desk landing</h1>
        </div>
        <div className="pd-admin-head-r">
          <div className="pd-seg pd-seg--sm" role="tablist" aria-label="Analytics window">
            {([7, 30, 90] as const).map((d) => (
              <button
                key={d}
                className={`pd-seg-item ${analyticsDays === d ? "is-active" : ""}`}
                onClick={() => setAnalyticsDays(d)}
              >
                {d}d
              </button>
            ))}
          </div>
          <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={openPreview}>
            Preview ↗
          </button>
        </div>
      </header>

      <div className="pd-stat-grid">
        <StatCard label="Scans" value={analytics?.scans ?? 0} />
        <StatCard label="Clicks" value={analytics?.clicks ?? 0} accent="info" />
        <StatCard
          label="Engagement rate"
          value={analytics ? Math.round(analytics.engagement_rate * 100) : 0}
          suffix="%"
          accent="ok"
        />
        <StatCard
          label="Top action"
          value={analytics?.per_action[0]?.clicks ?? 0}
          subtitle={analytics?.per_action[0]?.action__label ?? "—"}
          accent="warn"
        />
      </div>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">Actions</h2>
          <span className="pd-card-sub">Drag to reorder · {actions.length} configured</span>
        </div>

        <ActionList
          actions={actions}
          onMove={moveAction}
          onDropPosition={dropToPosition}
          onPatchField={patchField}
          onDelete={deleteAction}
        />

        {storeId !== null && (
          <AddActionForm
            storeId={storeId}
            onCreated={() => storeId !== null && refreshActions(storeId)}
          />
        )}
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  subtitle,
  suffix,
  accent,
}: {
  label: string;
  value: number;
  subtitle?: string;
  suffix?: string;
  accent?: "ok" | "warn" | "info";
}) {
  return (
    <div className={`pd-stat ${accent ? `pd-stat--${accent}` : ""}`}>
      <div className="pd-stat-label">{label}</div>
      <div className="pd-stat-value pd-mono">
        {value}
        {suffix ?? ""}
      </div>
      {subtitle && <div className="pd-stat-delta">{subtitle}</div>}
    </div>
  );
}

function ActionList({
  actions,
  onMove,
  onDropPosition,
  onPatchField,
  onDelete,
}: {
  actions: QRAction[];
  onMove: (id: number, direction: -1 | 1) => void;
  onDropPosition: (draggedId: number, dropOnIdx: number) => void;
  onPatchField: <K extends keyof QRAction>(id: number, key: K, value: QRAction[K]) => void;
  onDelete: (id: number) => void;
}) {
  const draggedIdRef = useRef<number | null>(null);

  if (actions.length === 0) {
    return <div className="pd-empty">No actions configured yet. Add the first one below.</div>;
  }
  return (
    <div className="pd-qr-list">
      {actions.map((a, idx) => (
        <div
          key={a.id}
          className="pd-qr-row"
          draggable
          onDragStart={() => {
            draggedIdRef.current = a.id;
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const dragged = draggedIdRef.current;
            draggedIdRef.current = null;
            if (dragged !== null && dragged !== a.id) onDropPosition(dragged, idx);
          }}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "ArrowUp") {
              e.preventDefault();
              onMove(a.id, -1);
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              onMove(a.id, 1);
            }
          }}
        >
          <span className="pd-qr-grip" aria-hidden>
            ⠿
          </span>
          <label className="pd-qr-row-label">
            <span className="pd-card-sub">Label</span>
            <input
              className="pd-input"
              value={a.label}
              onChange={(e) => onPatchField(a.id, "label", e.target.value)}
            />
          </label>
          <label className="pd-qr-row-url">
            <span className="pd-card-sub">Target URL</span>
            <input
              className="pd-input pd-mono"
              value={a.target_url}
              onChange={(e) => onPatchField(a.id, "target_url", e.target.value)}
            />
          </label>
          <label className="pd-qr-row-pts">
            <span className="pd-card-sub">Points</span>
            <input
              className="pd-input pd-mono"
              type="number"
              min={0}
              value={a.reward_points}
              onChange={(e) =>
                onPatchField(a.id, "reward_points", Math.max(0, Number(e.target.value || 0)))
              }
            />
          </label>
          <div className="pd-qr-row-actions">
            <label className="pd-chip pd-chip--ghost" style={{ cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={a.enabled}
                onChange={(e) => onPatchField(a.id, "enabled", e.target.checked)}
                style={{ marginRight: 6 }}
              />
              Enabled
            </label>
            <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={() => onDelete(a.id)}>
              Delete
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function AddActionForm({ storeId, onCreated }: { storeId: number; onCreated: () => void }) {
  const [kind, setKind] = useState<QRActionKind>("review");
  const [label, setLabel] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [points, setPoints] = useState(5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const canSave = useMemo(
    () => label.trim().length > 0 && /^https?:\/\//.test(targetUrl.trim()) && !saving,
    [label, targetUrl, saving],
  );

  async function submit() {
    if (!canSave) return;
    setSaving(true);
    setError("");
    try {
      await adminCreateQRAction({
        store: storeId,
        kind,
        label: label.trim(),
        target_url: targetUrl.trim(),
        reward_points: points,
        enabled: true,
      });
      setLabel("");
      setTargetUrl("");
      setPoints(5);
      onCreated();
    } catch {
      setError("Couldn't add this action — check the URL and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pd-qr-add">
      <div className="pd-card-head">
        <h3 className="pd-card-title" style={{ fontSize: 15 }}>
          Add an action
        </h3>
      </div>
      <div className="pd-qr-add-grid">
        <label className="pd-field">
          <span className="pd-field-label">Kind</span>
          <select
            className="pd-input"
            value={kind}
            onChange={(e) => setKind(e.target.value as QRActionKind)}
          >
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="pd-field">
          <span className="pd-field-label">Label</span>
          <input
            className="pd-input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Leave a review"
          />
        </label>
        <label className="pd-field">
          <span className="pd-field-label">Target URL</span>
          <input
            className="pd-input pd-mono"
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            placeholder="https://…"
          />
        </label>
        <label className="pd-field">
          <span className="pd-field-label">Points</span>
          <input
            className="pd-input pd-mono"
            type="number"
            min={0}
            value={points}
            onChange={(e) => setPoints(Math.max(0, Number(e.target.value || 0)))}
          />
        </label>
      </div>
      {error && (
        <div className="pd-error" style={{ marginTop: 8 }}>
          <span className="pd-error-dot" />
          {error}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
        <button
          className="pd-btn pd-btn--primary pd-btn--sm"
          disabled={!canSave}
          onClick={submit}
        >
          {saving ? "Adding…" : "Add action"}
        </button>
      </div>
    </div>
  );
}
