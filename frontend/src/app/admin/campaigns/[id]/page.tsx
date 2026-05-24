"use client";

// /admin/campaigns/[id] — header with status / totals / sent_at /
// sent_by + paginated `CampaignRun` table with status filter chips
// (All / Sent / Failed / Skipped opt-out) and a refresh button.
//
// Cancel button is shown for draft / scheduled campaigns. There is no
// edit on this page — staff edit drafts from the new-campaign flow
// re-creation pattern, and once sent, edits are refused by the backend.

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { fmtDate, relTime } from "@/components/pd-ui";
import {
  adminCancelCampaign,
  adminGetCampaign,
  adminListCampaignRuns,
  type Campaign,
  type CampaignRun,
  type CampaignRunStatus,
  type CampaignStatus,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useCurrentStore } from "@/lib/store-context";

const PAGE_SIZE = 50;

const STATUS_TONE: Record<CampaignStatus, string> = {
  draft: "pd-badge--muted",
  scheduled: "pd-badge--info",
  sending: "pd-badge--warn",
  sent: "pd-badge--ok",
  cancelled: "pd-badge--muted",
};

const RUN_STATUS_TONE: Record<CampaignRunStatus, string> = {
  queued: "pd-badge--muted",
  sent: "pd-badge--ok",
  failed: "pd-badge--warn",
  skipped_optout: "pd-badge--muted",
};

const FILTERS: { value: CampaignRunStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "sent", label: "Sent" },
  { value: "failed", label: "Failed" },
  { value: "skipped_optout", label: "Skipped opt-out" },
];

export default function CampaignDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const idStr = params?.id;
  const campaignId = useMemo(() => (idStr ? Number(idStr) : NaN), [idStr]);

  const { user, ready: authReady } = useAuth();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [runs, setRuns] = useState<CampaignRun[]>([]);
  const [runsCount, setRunsCount] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<CampaignRunStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // v6 multi-location: refetch when the admin switches store. A campaign
  // from a different store will 404 (handled by the existing error state).
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;

  const refresh = useCallback(async () => {
    if (!Number.isFinite(campaignId)) return;
    setLoading(true);
    setError(false);
    try {
      const [c, r] = await Promise.all([
        adminGetCampaign(campaignId),
        adminListCampaignRuns(campaignId, {
          status: statusFilter === "all" ? undefined : statusFilter,
          page,
          page_size: PAGE_SIZE,
        }),
      ]);
      setCampaign(c);
      setRuns(r.results);
      setRunsCount(r.count);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
    // storeSlug included so a store switch triggers refetch with the new scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, page, statusFilter, storeSlug]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCancel() {
    if (!campaign) return;
    if (!confirm("Cancel this campaign? It will not be sent.")) return;
    try {
      const updated = await adminCancelCampaign(campaign.id);
      setCampaign(updated);
    } catch (err) {
      alert(
        err instanceof Error
          ? err.message
          : "Couldn't cancel this campaign — it may already have been sent.",
      );
    }
  }

  const totalPages = Math.max(1, Math.ceil(runsCount / PAGE_SIZE));

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Campaign</div>
          <h1 className="pd-admin-title">{campaign?.name ?? `#${campaignId}`}</h1>
        </div>
        <div className="pd-admin-head-r">
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={() => router.push("/admin/campaigns")}
          >
            ← All campaigns
          </button>
          <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={() => void refresh()}>
            ↻ Refresh
          </button>
          {campaign && (campaign.status === "draft" || campaign.status === "scheduled") && (
            <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={handleCancel}>
              Cancel
            </button>
          )}
        </div>
      </header>

      {loading && !campaign && <div className="pd-empty">Loading campaign…</div>}
      {error && (
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load this campaign.
        </div>
      )}

      {campaign && (
        <>
          <div className="pd-stat-grid">
            <div className="pd-stat">
              <div className="pd-stat-label">Status</div>
              <div>
                <span className={`pd-badge ${STATUS_TONE[campaign.status]}`}>
                  {campaign.status}
                </span>
              </div>
            </div>
            <div className="pd-stat">
              <div className="pd-stat-label">Recipients</div>
              <div className="pd-stat-value pd-mono">{campaign.recipient_snapshot_count}</div>
            </div>
            <div className="pd-stat pd-stat--ok">
              <div className="pd-stat-label">Sent</div>
              <div className="pd-stat-value pd-mono">
                {campaign.sent_at ? fmtDate(campaign.sent_at) : "—"}
              </div>
              {campaign.sent_at && (
                <div className="pd-stat-delta">{relTime(campaign.sent_at)}</div>
              )}
            </div>
            <div className="pd-stat">
              <div className="pd-stat-label">Sent by</div>
              <div className="pd-stat-value">{campaign.sent_by_username ?? "—"}</div>
            </div>
          </div>

          <section className="pd-card">
            <div className="pd-card-head">
              <h2 className="pd-card-title">Body template</h2>
              <span className="pd-card-sub">Segment: {campaign.segment_name}</span>
            </div>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                fontFamily: "var(--font-mono, ui-monospace)",
                fontSize: 13,
                margin: 0,
              }}
            >
              {campaign.body_template}
            </pre>
          </section>

          <section className="pd-card">
            <div className="pd-card-head pd-card-head--filters">
              <div>
                <h2 className="pd-card-title">Recipients</h2>
                <span className="pd-card-sub">
                  {runsCount} run{runsCount === 1 ? "" : "s"} · page {page} of {totalPages}
                </span>
              </div>
              <div className="pd-filters">
                <div className="pd-filter">
                  <span className="pd-filter-label">Status</span>
                  <div className="pd-seg pd-seg--sm">
                    {FILTERS.map((f) => (
                      <button
                        key={f.value}
                        className={`pd-seg-item ${statusFilter === f.value ? "is-active" : ""}`}
                        onClick={() => {
                          setStatusFilter(f.value);
                          setPage(1);
                        }}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="pd-table">
              <div
                className="pd-tr pd-tr--head"
                style={{
                  display: "grid",
                  gridTemplateColumns: "1.5fr 1.2fr 0.8fr 1.2fr 1fr",
                }}
              >
                <div className="pd-th">Customer</div>
                <div className="pd-th">Phone</div>
                <div className="pd-th">Status</div>
                <div className="pd-th">Outbound id / reason</div>
                <div className="pd-th">Sent</div>
              </div>
              {runs.length === 0 && (
                <div className="pd-table-empty">No runs match this filter.</div>
              )}
              {runs.map((r) => (
                <div
                  key={r.id}
                  className="pd-tr"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.5fr 1.2fr 0.8fr 1.2fr 1fr",
                  }}
                >
                  <div className="pd-td pd-td-strong">{r.customer_name || "—"}</div>
                  <div className="pd-td pd-mono">{r.customer_phone}</div>
                  <div className="pd-td">
                    <span className={`pd-badge ${RUN_STATUS_TONE[r.status]}`}>{r.status}</span>
                  </div>
                  <div className="pd-td pd-mono pd-td-sub">
                    {r.status === "failed"
                      ? r.failure_reason || "—"
                      : r.outbound_message_id || "—"}
                  </div>
                  <div className="pd-td pd-td-sub">
                    {r.sent_at ? relTime(r.sent_at) : "—"}
                  </div>
                </div>
              ))}
            </div>

            {totalPages > 1 && (
              <div className="pd-preview-foot">
                <button
                  className="pd-btn pd-btn--ghost pd-btn--sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  ← Prev
                </button>
                <button
                  className="pd-btn pd-btn--ghost pd-btn--sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Next →
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
