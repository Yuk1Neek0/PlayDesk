"use client";

// /admin/segments — list of saved customer segments + "new segment"
// button that opens the SegmentBuilder modal. Each row shows the live
// match count fetched via /preview/?limit=1, the creator, and the
// created_at relative time.
//
// The store id is inferred from the first resource, mirroring the QR
// admin page — a multi-store selector is a future slice.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { fmtDate, relTime } from "@/components/pd-ui";
import { SegmentBuilder } from "@/components/admin/segment-builder";
import {
  adminDeleteSegment,
  adminListSegments,
  adminPreviewSegment,
  listResources,
  type Segment,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useCurrentStore } from "@/lib/store-context";

interface Row extends Segment {
  match_count: number | null;
}

export default function AdminSegmentsPage() {
  const [storeId, setStoreId] = useState<number | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState<Segment | "new" | null>(null);

  const { user, ready: authReady } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

  const loadAll = useCallback(async (sid: number) => {
    setLoading(true);
    setError(false);
    try {
      const page = await adminListSegments({ store: sid });
      // Fetch preview counts in parallel — limited to 1 row per call to
      // keep payloads small.
      const counts = await Promise.all(
        page.results.map((s) =>
          adminPreviewSegment(s.id, 1)
            .then((p) => p.count)
            .catch(() => null),
        ),
      );
      setRows(page.results.map((s, i) => ({ ...s, match_count: counts[i] })));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  // v6 multi-location: prefer the active store from <StoreProvider>;
  // fall back to deriving from the first resource for single-store deployments.
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

  useEffect(() => {
    if (storeId === null) return;
    void loadAll(storeId);
  }, [storeId, loadAll]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this segment? Any campaigns using it must be deleted first.")) return;
    try {
      await adminDeleteSegment(id);
      if (storeId !== null) await loadAll(storeId);
    } catch (err) {
      alert(
        err instanceof Error
          ? err.message
          : "Couldn't delete this segment — it may still be referenced by a campaign.",
      );
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Campaigns</div>
          <h1 className="pd-admin-title">Customer segments</h1>
        </div>
        <div className="pd-admin-head-r">
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            onClick={() => setEditing("new")}
            disabled={storeId === null}
          >
            + New segment
          </button>
        </div>
      </header>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">Saved segments</h2>
          <span className="pd-card-sub">{rows.length} total</span>
        </div>

        {loading && <div className="pd-empty">Loading segments…</div>}
        {error && (
          <div className="pd-error">
            <span className="pd-error-dot" />
            Couldn&apos;t load segments. Refresh to try again.
          </div>
        )}

        {!loading && !error && (
          <div className="pd-table">
            <div
              className="pd-tr pd-tr--head"
              style={{ display: "grid", gridTemplateColumns: "1.6fr 0.8fr 1.2fr 1.2fr 0.6fr" }}
            >
              <div className="pd-th">Name</div>
              <div className="pd-th">Matches</div>
              <div className="pd-th">Created by</div>
              <div className="pd-th">Created</div>
              <div className="pd-th pd-th--right">Actions</div>
            </div>
            {rows.length === 0 && (
              <div className="pd-table-empty">No segments yet. Create your first one above.</div>
            )}
            {rows.map((r) => (
              <div
                key={r.id}
                className="pd-tr"
                style={{ display: "grid", gridTemplateColumns: "1.6fr 0.8fr 1.2fr 1.2fr 0.6fr" }}
              >
                <div className="pd-td pd-td-strong">{r.name}</div>
                <div className="pd-td pd-mono">
                  {r.match_count === null ? "—" : r.match_count}
                </div>
                <div className="pd-td">{r.created_by_username ?? "—"}</div>
                <div className="pd-td pd-td-sub">
                  {relTime(r.created_at)}
                  <div className="pd-td-sub pd-mono">{fmtDate(r.created_at)}</div>
                </div>
                <div className="pd-td pd-td--right" style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => setEditing(r)}
                  >
                    Edit
                  </button>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => handleDelete(r.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {editing !== null && storeId !== null && (
        <SegmentBuilder
          storeId={storeId}
          initial={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void loadAll(storeId);
          }}
        />
      )}
    </div>
  );
}
