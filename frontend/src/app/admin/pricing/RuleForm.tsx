"use client";

// RuleForm — admin form for creating / editing a pricing rule.
// Dynamic params section per rule_type (5 form fragments). Deliberately
// explicit — five small inline blocks read more clearly than a registry
// of form generators for this size of schema set.

import { useEffect, useState } from "react";

import { type PricingRule, type PricingRuleType } from "@/lib/api";

const DAY_LABELS: { key: string; label: string }[] = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
];

const RULE_TYPE_LABELS: Record<PricingRuleType, string> = {
  peak_hours: "Peak hours (surcharge or discount in a time window)",
  day_of_week: "Day of week (flat rate or % off on selected weekdays)",
  member_tier: "Member tier (% off for a customer tier)",
  min_duration: "Min duration (% off when booking ≥ N hours)",
  bracket_rate: "Bracket rate (tiered per-hour rate)",
};

export interface DraftRule {
  id: number | null; // null = new
  name: string;
  description: string;
  enabled: boolean;
  priority: number;
  stackable: boolean;
  rule_type: PricingRuleType;
  params: Record<string, unknown>;
}

export const BLANK_DRAFT: DraftRule = {
  id: null,
  name: "",
  description: "",
  enabled: true,
  priority: 100,
  stackable: true,
  rule_type: "peak_hours",
  params: {
    days: ["fri", "sat"],
    start_hour: 20,
    end_hour: 24,
    adjustment_pct: 20,
  },
};

export function ruleToDraft(r: PricingRule): DraftRule {
  return {
    id: r.id,
    name: r.name,
    description: r.description,
    enabled: r.enabled,
    priority: r.priority,
    stackable: r.stackable,
    rule_type: r.rule_type,
    params: r.params,
  };
}

const DEFAULT_PARAMS: Record<PricingRuleType, Record<string, unknown>> = {
  peak_hours: { days: ["fri", "sat"], start_hour: 20, end_hour: 24, adjustment_pct: 20 },
  day_of_week: { days: ["tue"], discount_pct: 20 },
  member_tier: { tier_id: 1, discount_pct: 15 },
  min_duration: { min_hours: 3, discount_pct: 20 },
  bracket_rate: {
    brackets: [
      { max_hours: 2, rate: "50" },
      { max_hours: null, rate: "30" },
    ],
  },
};

export default function RuleForm({
  draft,
  onChange,
  onClose,
  onSave,
  saving,
  error,
}: {
  draft: DraftRule;
  onChange: (d: DraftRule) => void;
  onClose: () => void;
  onSave: () => void;
  saving: boolean;
  error: string;
}) {
  // Whenever the rule_type changes, reset params to that type's defaults
  // — otherwise the leftover shape would 400 on save.
  const [lastType, setLastType] = useState<PricingRuleType>(draft.rule_type);
  useEffect(() => {
    if (draft.rule_type !== lastType) {
      onChange({ ...draft, params: { ...DEFAULT_PARAMS[draft.rule_type] } });
      setLastType(draft.rule_type);
    }
  }, [draft, lastType, onChange]);

  const canSave = draft.name.trim().length > 0 && !saving;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={draft.id === null ? "New pricing rule" : "Edit pricing rule"}
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
        style={{ maxWidth: 640, width: "100%", maxHeight: "85vh", overflow: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pd-card-head">
          <h3 className="pd-card-title">
            {draft.id === null ? "New pricing rule" : "Edit pricing rule"}
          </h3>
          <button
            className="pd-btn pd-btn--ghost pd-btn--sm"
            onClick={onClose}
            aria-label="Close"
          >
            Close
          </button>
        </div>

        <label className="pd-field" style={{ marginBottom: 10 }}>
          <span className="pd-field-label">Name</span>
          <input
            className="pd-input"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
          />
        </label>

        <label className="pd-field" style={{ marginBottom: 10 }}>
          <span className="pd-field-label">Description</span>
          <textarea
            className="pd-input"
            rows={2}
            value={draft.description}
            onChange={(e) => onChange({ ...draft, description: e.target.value })}
          />
        </label>

        <label className="pd-field" style={{ marginBottom: 10 }}>
          <span className="pd-field-label">Rule type</span>
          <select
            className="pd-input"
            value={draft.rule_type}
            onChange={(e) =>
              onChange({ ...draft, rule_type: e.target.value as PricingRuleType })
            }
          >
            {Object.entries(RULE_TYPE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <div
          style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 10 }}
        >
          <label className="pd-field">
            <span className="pd-field-label">Priority</span>
            <input
              type="number"
              className="pd-input pd-mono"
              value={draft.priority}
              min={0}
              onChange={(e) =>
                onChange({ ...draft, priority: Math.max(0, Number(e.target.value || 0)) })
              }
            />
          </label>
          <label className="pd-chip pd-chip--ghost" style={{ cursor: "pointer", alignSelf: "end" }}>
            <input
              type="checkbox"
              checked={draft.stackable}
              onChange={(e) => onChange({ ...draft, stackable: e.target.checked })}
              style={{ marginRight: 6 }}
            />
            Stackable
          </label>
          <label className="pd-chip pd-chip--ghost" style={{ cursor: "pointer", alignSelf: "end" }}>
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => onChange({ ...draft, enabled: e.target.checked })}
              style={{ marginRight: 6 }}
            />
            Enabled
          </label>
        </div>

        <div className="pd-card" style={{ padding: 10, marginBottom: 10 }}>
          <div className="pd-eyebrow" style={{ marginBottom: 6 }}>
            Params · {draft.rule_type}
          </div>
          <ParamsFragment draft={draft} onChange={onChange} />
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

// Per-rule_type params editor. Explicit small fragments — easier to read
// than a config-driven generator at this size.
function ParamsFragment({
  draft,
  onChange,
}: {
  draft: DraftRule;
  onChange: (d: DraftRule) => void;
}) {
  const setP = (patch: Record<string, unknown>) =>
    onChange({ ...draft, params: { ...draft.params, ...patch } });

  if (draft.rule_type === "peak_hours") {
    return (
      <PeakHoursParams draft={draft} setP={setP} />
    );
  }
  if (draft.rule_type === "day_of_week") {
    return <DayOfWeekParams draft={draft} setP={setP} />;
  }
  if (draft.rule_type === "member_tier") {
    return <MemberTierParams draft={draft} setP={setP} />;
  }
  if (draft.rule_type === "min_duration") {
    return <MinDurationParams draft={draft} setP={setP} />;
  }
  return <BracketRateParams draft={draft} onChange={onChange} />;
}

function DayPicker({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (key: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {DAY_LABELS.map((d) => (
        <label
          key={d.key}
          className={`pd-chip pd-chip--ghost ${selected.includes(d.key) ? "is-active" : ""}`}
          style={{ cursor: "pointer" }}
        >
          <input
            type="checkbox"
            checked={selected.includes(d.key)}
            onChange={() => onToggle(d.key)}
            style={{ marginRight: 4 }}
          />
          {d.label}
        </label>
      ))}
    </div>
  );
}

function PeakHoursParams({
  draft,
  setP,
}: {
  draft: DraftRule;
  setP: (p: Record<string, unknown>) => void;
}) {
  const days = (draft.params.days as string[]) ?? [];
  return (
    <>
      <div className="pd-field-label">Days</div>
      <DayPicker
        selected={days}
        onToggle={(k) =>
          setP({ days: days.includes(k) ? days.filter((x) => x !== k) : [...days, k] })
        }
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 8 }}>
        <label className="pd-field">
          <span className="pd-field-label">Start hour</span>
          <input
            type="number"
            min={0}
            max={24}
            className="pd-input pd-mono"
            value={Number(draft.params.start_hour ?? 0)}
            onChange={(e) => setP({ start_hour: Number(e.target.value) })}
          />
        </label>
        <label className="pd-field">
          <span className="pd-field-label">End hour</span>
          <input
            type="number"
            min={0}
            max={24}
            className="pd-input pd-mono"
            value={Number(draft.params.end_hour ?? 0)}
            onChange={(e) => setP({ end_hour: Number(e.target.value) })}
          />
        </label>
        <label className="pd-field">
          <span className="pd-field-label">Adjustment % (signed)</span>
          <input
            type="number"
            className="pd-input pd-mono"
            value={Number(draft.params.adjustment_pct ?? 0)}
            onChange={(e) => setP({ adjustment_pct: Number(e.target.value) })}
          />
        </label>
      </div>
    </>
  );
}

function DayOfWeekParams({
  draft,
  setP,
}: {
  draft: DraftRule;
  setP: (p: Record<string, unknown>) => void;
}) {
  const days = (draft.params.days as string[]) ?? [];
  const mode = "flat_rate" in draft.params ? "flat" : "pct";
  return (
    <>
      <div className="pd-field-label">Days</div>
      <DayPicker
        selected={days}
        onToggle={(k) =>
          setP({ days: days.includes(k) ? days.filter((x) => x !== k) : [...days, k] })
        }
      />
      <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
        <label className="pd-chip pd-chip--ghost" style={{ cursor: "pointer" }}>
          <input
            type="radio"
            name="dow-mode"
            checked={mode === "flat"}
            onChange={() => setP({ flat_rate: "30", discount_pct: undefined })}
            style={{ marginRight: 4 }}
          />
          Flat rate per hour
        </label>
        <label className="pd-chip pd-chip--ghost" style={{ cursor: "pointer" }}>
          <input
            type="radio"
            name="dow-mode"
            checked={mode === "pct"}
            onChange={() => setP({ discount_pct: 20, flat_rate: undefined })}
            style={{ marginRight: 4 }}
          />
          % discount
        </label>
      </div>
      {mode === "flat" ? (
        <label className="pd-field" style={{ marginTop: 8 }}>
          <span className="pd-field-label">Flat rate ($/hr)</span>
          <input
            className="pd-input pd-mono"
            value={String(draft.params.flat_rate ?? "")}
            onChange={(e) => setP({ flat_rate: e.target.value })}
          />
        </label>
      ) : (
        <label className="pd-field" style={{ marginTop: 8 }}>
          <span className="pd-field-label">Discount %</span>
          <input
            type="number"
            min={0}
            max={100}
            className="pd-input pd-mono"
            value={Number(draft.params.discount_pct ?? 0)}
            onChange={(e) => setP({ discount_pct: Number(e.target.value) })}
          />
        </label>
      )}
    </>
  );
}

function MemberTierParams({
  draft,
  setP,
}: {
  draft: DraftRule;
  setP: (p: Record<string, unknown>) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      <label className="pd-field">
        <span className="pd-field-label">Tier ID</span>
        <input
          type="number"
          min={1}
          className="pd-input pd-mono"
          value={Number(draft.params.tier_id ?? 0)}
          onChange={(e) => setP({ tier_id: Number(e.target.value) })}
        />
      </label>
      <label className="pd-field">
        <span className="pd-field-label">Discount %</span>
        <input
          type="number"
          min={0}
          max={100}
          className="pd-input pd-mono"
          value={Number(draft.params.discount_pct ?? 0)}
          onChange={(e) => setP({ discount_pct: Number(e.target.value) })}
        />
      </label>
    </div>
  );
}

function MinDurationParams({
  draft,
  setP,
}: {
  draft: DraftRule;
  setP: (p: Record<string, unknown>) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      <label className="pd-field">
        <span className="pd-field-label">Min hours</span>
        <input
          type="number"
          min={1}
          className="pd-input pd-mono"
          value={Number(draft.params.min_hours ?? 1)}
          onChange={(e) => setP({ min_hours: Number(e.target.value) })}
        />
      </label>
      <label className="pd-field">
        <span className="pd-field-label">Discount %</span>
        <input
          type="number"
          min={0}
          max={100}
          className="pd-input pd-mono"
          value={Number(draft.params.discount_pct ?? 0)}
          onChange={(e) => setP({ discount_pct: Number(e.target.value) })}
        />
      </label>
    </div>
  );
}

interface Bracket {
  max_hours: number | null;
  rate: string;
}

function BracketRateParams({
  draft,
  onChange,
}: {
  draft: DraftRule;
  onChange: (d: DraftRule) => void;
}) {
  const brackets = (draft.params.brackets as Bracket[]) ?? [];
  const update = (idx: number, patch: Partial<Bracket>) => {
    const next = brackets.map((b, i) => (i === idx ? { ...b, ...patch } : b));
    onChange({ ...draft, params: { ...draft.params, brackets: next } });
  };
  const add = () => {
    const next = [...brackets, { max_hours: null, rate: "30" }];
    onChange({ ...draft, params: { ...draft.params, brackets: next } });
  };
  const remove = (idx: number) => {
    const next = brackets.filter((_, i) => i !== idx);
    onChange({ ...draft, params: { ...draft.params, brackets: next } });
  };
  return (
    <>
      {brackets.map((b, idx) => (
        <div
          key={idx}
          style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, marginBottom: 6 }}
        >
          <label className="pd-field">
            <span className="pd-field-label">Up to (hours, blank = no cap)</span>
            <input
              className="pd-input pd-mono"
              value={b.max_hours == null ? "" : String(b.max_hours)}
              onChange={(e) =>
                update(idx, {
                  max_hours: e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          </label>
          <label className="pd-field">
            <span className="pd-field-label">Rate $/hr</span>
            <input
              className="pd-input pd-mono"
              value={b.rate}
              onChange={(e) => update(idx, { rate: e.target.value })}
            />
          </label>
          <button
            type="button"
            className="pd-btn pd-btn--ghost pd-btn--sm"
            style={{ alignSelf: "end" }}
            onClick={() => remove(idx)}
            aria-label={`Remove bracket ${idx + 1}`}
          >
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="pd-btn pd-btn--ghost pd-btn--sm" onClick={add}>
        + Add bracket
      </button>
    </>
  );
}
