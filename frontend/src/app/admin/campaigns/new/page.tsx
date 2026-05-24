"use client";

// /admin/campaigns/new — four-step create flow.
//
//   1. Pick segment (live count via /preview/?limit=1).
//   2. Compose body in a textarea with `{customer.name}` / `{store.name}`
//      hints.
//   3. Pick schedule — now (default) or a specific datetime-local.
//   4. Confirmation modal that shows recipient count + body rendered
//      against the first sample customer.
//
// The campaign is only created on confirm — there are no orphan drafts
// from this flow. After successful send, we navigate to /admin/campaigns
// to show the result in the list.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CampaignConfirmModal } from "@/components/admin/campaign-confirm-modal";
import {
  adminCreateCampaign,
  adminListSegments,
  adminPreviewSegment,
  adminSendCampaign,
  listResources,
  type Segment,
  type SegmentPreview,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useCurrentStore } from "@/lib/store-context";

type ScheduleMode = "now" | "later";

export default function NewCampaignPage() {
  const router = useRouter();
  const { user, ready: authReady } = useAuth();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

  const [storeId, setStoreId] = useState<number | null>(null);
  const [storeName, setStoreName] = useState("PlayDesk");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [pickedSegmentId, setPickedSegmentId] = useState<number | null>(null);
  const [preview, setPreview] = useState<SegmentPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("now");
  const [scheduledFor, setScheduledFor] = useState<string>("");

  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const pickedSegment = useMemo(
    () => segments.find((s) => s.id === pickedSegmentId) ?? null,
    [segments, pickedSegmentId],
  );

  // v6 multi-location: prefer the active store from <StoreProvider>;
  // fall back to deriving from the first resource for single-store deployments.
  const { current } = useCurrentStore();
  const currentStoreId = current?.id ?? null;
  const currentName = current?.name ?? null;

  useEffect(() => {
    let cancelled = false;
    if (currentStoreId !== null) {
      setStoreId(currentStoreId);
      if (currentName) setStoreName(currentName);
      return () => {
        cancelled = true;
      };
    }
    listResources()
      .then((page) => {
        if (cancelled) return;
        const first = page.results[0];
        if (!first) return;
        setStoreId(first.store_id);
      })
      .catch(() => {
        /* leave storeId null — submit will error */
      });
    return () => {
      cancelled = true;
    };
  }, [currentStoreId, currentName]);

  useEffect(() => {
    if (storeId === null) return;
    let cancelled = false;
    adminListSegments({ store: storeId })
      .then((page) => {
        if (!cancelled) setSegments(page.results);
      })
      .catch(() => {
        /* segments stay empty — UI will reflect */
      });
    return () => {
      cancelled = true;
    };
  }, [storeId]);

  // Whenever the picked segment changes, refresh the preview.
  useEffect(() => {
    if (pickedSegmentId === null) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    adminPreviewSegment(pickedSegmentId, 1)
      .then((p) => {
        if (!cancelled) setPreview(p);
      })
      .catch(() => {
        if (!cancelled) setPreview(null);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pickedSegmentId]);

  // Pick a sensible default for the schedule input the moment the user
  // switches to "later".
  useEffect(() => {
    if (scheduleMode === "later" && scheduledFor === "") {
      const d = new Date(Date.now() + 60 * 60 * 1000);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const hh = String(d.getHours()).padStart(2, "0");
      const mi = String(d.getMinutes()).padStart(2, "0");
      setScheduledFor(`${yyyy}-${mm}-${dd}T${hh}:${mi}`);
    }
  }, [scheduleMode, scheduledFor]);

  // Try to learn the actual store name (cosmetic; falls back to "PlayDesk").
  useEffect(() => {
    if (storeId === null) return;
    listResources({ store_id: storeId })
      .then((page) => {
        const r = page.results[0];
        if (r) setStoreName(r.name.split(" / ")[0] ?? "PlayDesk");
      })
      .catch(() => {});
  }, [storeId]);

  const canShowConfirm =
    storeId !== null &&
    pickedSegmentId !== null &&
    name.trim().length > 0 &&
    body.trim().length > 0 &&
    (preview?.count ?? 0) > 0;

  async function handleConfirm() {
    if (!pickedSegment || storeId === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await adminCreateCampaign({
        store_id: storeId,
        segment_id: pickedSegment.id,
        name: name.trim(),
        body_template: body,
        scheduled_for:
          scheduleMode === "later" && scheduledFor !== ""
            ? new Date(scheduledFor).toISOString()
            : undefined,
      });
      await adminSendCampaign(created.id);
      router.push(`/admin/campaigns/${created.id}`);
    } catch (err) {
      setSubmitError(
        err instanceof Error
          ? err.message
          : "Couldn't send this campaign. Try again or check the inputs.",
      );
      setSubmitting(false);
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">New campaign</div>
          <h1 className="pd-admin-title">Compose & send</h1>
        </div>
        <div className="pd-admin-head-r">
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={() => router.push("/admin/campaigns")}
          >
            Back to list
          </button>
        </div>
      </header>

      {/* Step 1 — segment */}
      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">1. Pick a segment</h2>
          <span className="pd-card-sub">
            {preview ? `${preview.count} match${preview.count === 1 ? "" : "es"}` : "—"}
          </span>
        </div>
        {segments.length === 0 ? (
          <div className="pd-empty">
            No segments yet — create one on{" "}
            <a href="/admin/segments" style={{ textDecoration: "underline" }}>
              /admin/segments
            </a>
            .
          </div>
        ) : (
          <div className="pd-field">
            <select
              className="pd-input"
              value={pickedSegmentId === null ? "" : String(pickedSegmentId)}
              onChange={(e) =>
                setPickedSegmentId(e.target.value === "" ? null : Number(e.target.value))
              }
            >
              <option value="">— Choose a segment —</option>
              {segments.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {previewLoading && (
              <div className="pd-card-sub" style={{ marginTop: 6 }}>
                Counting matches…
              </div>
            )}
          </div>
        )}
      </section>

      {/* Step 2 — body */}
      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">2. Draft the message</h2>
          <span className="pd-card-sub">
            Use {"{customer.name}"} or {"{store.name}"} for personalization.
          </span>
        </div>
        <div className="pd-field" style={{ marginBottom: 8 }}>
          <span className="pd-field-label">Campaign name (internal)</span>
          <input
            className="pd-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. May VIP drop"
          />
        </div>
        <div className="pd-field">
          <span className="pd-field-label">Message body</span>
          <textarea
            className="pd-input"
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Hi {customer.name}, we've got a fresh tournament drop at {store.name} this Friday — reply YES to reserve a slot."
          />
          <span className="pd-card-sub" style={{ marginTop: 4 }}>
            {body.length} characters · {body.trim().length === 0 ? "empty" : "ready"}
          </span>
        </div>
      </section>

      {/* Step 3 — schedule */}
      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">3. Schedule</h2>
        </div>
        <div className="pd-seg pd-seg--sm" style={{ marginBottom: 8 }}>
          <button
            className={`pd-seg-item ${scheduleMode === "now" ? "is-active" : ""}`}
            onClick={() => setScheduleMode("now")}
          >
            Send now
          </button>
          <button
            className={`pd-seg-item ${scheduleMode === "later" ? "is-active" : ""}`}
            onClick={() => setScheduleMode("later")}
          >
            Schedule for later
          </button>
        </div>
        {scheduleMode === "later" && (
          <input
            className="pd-input pd-mono"
            type="datetime-local"
            value={scheduledFor}
            onChange={(e) => setScheduledFor(e.target.value)}
          />
        )}
        {scheduleMode === "later" && (
          <div className="pd-card-sub" style={{ marginTop: 6 }}>
            Note: v4 only sends synchronously. The scheduled time is recorded but the send
            happens on confirm.
          </div>
        )}
      </section>

      {/* Step 4 — confirm */}
      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">4. Send</h2>
        </div>
        <button
          className="pd-btn pd-btn--primary"
          disabled={!canShowConfirm}
          onClick={() => setShowConfirm(true)}
        >
          Review &amp; send
        </button>
      </section>

      {showConfirm && pickedSegment && (
        <CampaignConfirmModal
          segmentName={pickedSegment.name}
          body={body}
          count={preview?.count ?? 0}
          sample={preview?.sample[0] ?? null}
          storeName={storeName}
          scheduledFor={scheduleMode === "later" ? scheduledFor : null}
          onCancel={() => {
            if (!submitting) setShowConfirm(false);
          }}
          onConfirm={handleConfirm}
          submitting={submitting}
          submitError={submitError}
        />
      )}
    </div>
  );
}
