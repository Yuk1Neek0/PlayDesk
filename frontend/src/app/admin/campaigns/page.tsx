"use client";

// /admin/campaigns — list of all campaigns with status chip, segment
// name, scheduled_for, recipient_snapshot_count, sent_at. Row click
// navigates to /admin/campaigns/[id]. Top-right "New campaign" launches
// the four-step new-campaign flow at /admin/campaigns/new.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fmtDate, relTime } from "@/components/pd-ui";
import {
  adminListCampaigns,
  listResources,
  type Campaign,
  type CampaignStatus,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useCurrentStore } from "@/lib/store-context";

const STATUS_TONE: Record<CampaignStatus, string> = {
  draft: "pd-badge--muted",
  scheduled: "pd-badge--info",
  sending: "pd-badge--warn",
  sent: "pd-badge--ok",
  cancelled: "pd-badge--muted",
};

const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "Draft",
  scheduled: "Scheduled",
  sending: "Sending…",
  sent: "Sent",
  cancelled: "Cancelled",
};

export default function AdminCampaignsPage() {
  const [storeId, setStoreId] = useState<number | null>(null);
  const [rows, setRows] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const { user, ready: authReady } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

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
    let cancelled = false;
    setLoading(true);
    setError(false);
    adminListCampaigns({ store: storeId })
      .then((page) => {
        if (cancelled) return;
        setRows(page.results);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [storeId]);

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Campaigns</div>
          <h1 className="pd-admin-title">Marketing sends</h1>
        </div>
        <div className="pd-admin-head-r">
          <Link className="pd-btn pd-btn--ghost pd-btn--sm" href="/admin/segments">
            Manage segments
          </Link>
          <Link className="pd-btn pd-btn--primary pd-btn--sm" href="/admin/campaigns/new">
            + New campaign
          </Link>
        </div>
      </header>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">All campaigns</h2>
          <span className="pd-card-sub">{rows.length} total</span>
        </div>

        {loading && <div className="pd-empty">Loading campaigns…</div>}
        {error && (
          <div className="pd-error">
            <span className="pd-error-dot" />
            Couldn&apos;t load campaigns. Refresh to try again.
          </div>
        )}

        {!loading && !error && (
          <div className="pd-table">
            <div
              className="pd-tr pd-tr--head"
              style={{
                display: "grid",
                gridTemplateColumns: "1.4fr 0.8fr 1.2fr 1fr 0.8fr 1fr",
              }}
            >
              <div className="pd-th">Name</div>
              <div className="pd-th">Status</div>
              <div className="pd-th">Segment</div>
              <div className="pd-th">Scheduled</div>
              <div className="pd-th">Recipients</div>
              <div className="pd-th">Sent</div>
            </div>
            {rows.length === 0 && (
              <div className="pd-table-empty">
                No campaigns yet. Create your first one above.
              </div>
            )}
            {rows.map((c) => (
              <Link
                key={c.id}
                className="pd-tr pd-tr--row"
                href={`/admin/campaigns/${c.id}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.4fr 0.8fr 1.2fr 1fr 0.8fr 1fr",
                }}
              >
                <div className="pd-td pd-td-strong">{c.name}</div>
                <div className="pd-td">
                  <span className={`pd-badge ${STATUS_TONE[c.status]}`}>
                    {STATUS_LABEL[c.status]}
                  </span>
                </div>
                <div className="pd-td">{c.segment_name}</div>
                <div className="pd-td pd-td-sub pd-mono">{fmtDate(c.scheduled_for)}</div>
                <div className="pd-td pd-mono">{c.recipient_snapshot_count}</div>
                <div className="pd-td pd-td-sub">
                  {c.sent_at ? relTime(c.sent_at) : "—"}
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
