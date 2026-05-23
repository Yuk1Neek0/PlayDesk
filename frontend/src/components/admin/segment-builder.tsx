"use client";

// Modal drawer for creating or editing a Segment. Tag chip selector +
// `min_total_visits` number + `last_visit_within_days` dropdown +
// `locale_pref` dropdown, with a 300ms-debounced live preview count.
//
// Preview is only available once the segment has been saved at least
// once (the backend route is /preview/ on an existing segment). For an
// unsaved segment, we POST a temporary one, preview it, then delete it
// — but that adds complexity for a hint UI; instead we hide the live
// count until first save and rely on the recipient-count step in the
// new-campaign flow for confidence.

import { useEffect, useMemo, useRef, useState } from "react";

import {
  adminCreateSegment,
  adminPreviewSegment,
  adminUpdateSegment,
  type Segment,
  type SegmentFilter,
} from "@/lib/api";

const PREVIEW_DEBOUNCE_MS = 300;

const LAST_VISIT_OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: "Any" },
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 60, label: "Last 60 days" },
  { value: 90, label: "Last 90 days" },
  { value: 365, label: "Last 365 days" },
];

const LOCALE_OPTIONS: { value: "" | "en" | "zh"; label: string }[] = [
  { value: "", label: "Any" },
  { value: "en", label: "EN" },
  { value: "zh", label: "中文" },
];

interface Props {
  storeId: number;
  // If editing, an existing segment; otherwise undefined for create.
  initial?: Segment;
  onClose: () => void;
  onSaved: (segment: Segment) => void;
}

export function SegmentBuilder({ storeId, initial, onClose, onSaved }: Props) {
  const [name, setName] = useState(initial?.name ?? "");
  const [tagsInput, setTagsInput] = useState(
    (initial?.filter.tags_include ?? []).join(", "),
  );
  const [minVisits, setMinVisits] = useState<string>(
    initial?.filter.min_total_visits != null ? String(initial.filter.min_total_visits) : "",
  );
  const [lastVisitDays, setLastVisitDays] = useState<number | null>(
    initial?.filter.last_visit_within_days ?? null,
  );
  const [locale, setLocale] = useState<"" | "en" | "zh">(initial?.filter.locale_pref ?? "");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Live preview state — populated only once the segment exists.
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Build the in-memory filter object from the controlled inputs.
  const filter: SegmentFilter = useMemo(() => {
    const out: SegmentFilter = {};
    const tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
    if (tags.length > 0) out.tags_include = tags;
    const m = Number(minVisits);
    if (minVisits !== "" && Number.isFinite(m) && m > 0) out.min_total_visits = m;
    if (lastVisitDays !== null) out.last_visit_within_days = lastVisitDays;
    if (locale !== "") out.locale_pref = locale;
    return out;
  }, [tagsInput, minVisits, lastVisitDays, locale]);

  // Debounced preview refresh — only meaningful once we have an id.
  useEffect(() => {
    if (!initial) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setPreviewLoading(true);
      try {
        // Save the filter as a draft update so the preview reflects the
        // current builder state. Skipped if the form is invalid.
        if (name.trim().length === 0) return;
        await adminUpdateSegment(initial.id, { filter });
        const p = await adminPreviewSegment(initial.id, 1);
        setPreviewCount(p.count);
      } catch {
        setPreviewCount(null);
      } finally {
        setPreviewLoading(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [filter, initial, name]);

  const canSave = name.trim().length > 0 && !saving;

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = initial
        ? await adminUpdateSegment(initial.id, { name: name.trim(), filter })
        : await adminCreateSegment({ store_id: storeId, name: name.trim(), filter });
      onSaved(saved);
    } catch (err) {
      setSaveError(
        err instanceof Error
          ? err.message
          : "Couldn't save this segment. Check the values and try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pd-modal-overlay" role="dialog" aria-modal="true">
      <div className="pd-modal">
        <div className="pd-card-head">
          <h2 className="pd-card-title">{initial ? "Edit segment" : "New segment"}</h2>
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="pd-field" style={{ marginBottom: 12 }}>
          <span className="pd-field-label">Name</span>
          <input
            className="pd-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Active VIPs"
            autoFocus
          />
        </div>

        <div className="pd-field" style={{ marginBottom: 12 }}>
          <span className="pd-field-label">Tags (comma-separated)</span>
          <input
            className="pd-input"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="vip, regular"
          />
          <span className="pd-card-sub" style={{ marginTop: 4 }}>
            Matches customers who have <em>all</em> of these tags.
          </span>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 12,
            marginBottom: 12,
          }}
        >
          <label className="pd-field">
            <span className="pd-field-label">Min total visits</span>
            <input
              className="pd-input pd-mono"
              type="number"
              min={0}
              value={minVisits}
              onChange={(e) => setMinVisits(e.target.value)}
              placeholder="0"
            />
          </label>
          <label className="pd-field">
            <span className="pd-field-label">Last visit within</span>
            <select
              className="pd-input"
              value={lastVisitDays === null ? "" : String(lastVisitDays)}
              onChange={(e) =>
                setLastVisitDays(e.target.value === "" ? null : Number(e.target.value))
              }
            >
              {LAST_VISIT_OPTIONS.map((o) => (
                <option key={o.label} value={o.value === null ? "" : String(o.value)}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="pd-field">
            <span className="pd-field-label">Locale</span>
            <select
              className="pd-input"
              value={locale}
              onChange={(e) => setLocale(e.target.value as "" | "en" | "zh")}
            >
              {LOCALE_OPTIONS.map((o) => (
                <option key={o.label} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {initial && (
          <div className="pd-card-sub" style={{ marginBottom: 12 }}>
            {previewLoading
              ? "Counting matches…"
              : previewCount !== null
                ? `${previewCount} customer${previewCount === 1 ? "" : "s"} match this filter.`
                : "Live count will appear after first save."}
          </div>
        )}

        {saveError && (
          <div className="pd-error" style={{ marginBottom: 12 }}>
            <span className="pd-error-dot" />
            {saveError}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={onClose}>
            Cancel
          </button>
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            disabled={!canSave}
            onClick={handleSave}
          >
            {saving ? "Saving…" : initial ? "Save changes" : "Create segment"}
          </button>
        </div>
      </div>
    </div>
  );
}
