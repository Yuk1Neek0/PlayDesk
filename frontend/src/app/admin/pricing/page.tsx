"use client";

// /admin/pricing — list + CRUD for the store's PricingRule rows + the
// QuoteSandbox at the bottom. Reorder uses up/down arrows (no new dep);
// the PRD doesn't require drag-and-drop specifically.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  adminCreatePricingRule,
  adminDeletePricingRule,
  adminListPricingRules,
  adminUpdatePricingRule,
  listResources,
  type PricingRule,
  type Resource,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

import QuoteSandbox from "./QuoteSandbox";
import RuleForm, { BLANK_DRAFT, ruleToDraft, type DraftRule } from "./RuleForm";

const RULE_TYPE_SHORT: Record<string, string> = {
  peak_hours: "Peak hours",
  day_of_week: "Day of week",
  member_tier: "Member tier",
  min_duration: "Min duration",
  bracket_rate: "Bracket rate",
};

export default function AdminPricingPage() {
  const [rules, setRules] = useState<PricingRule[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [draft, setDraft] = useState<DraftRule | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const { user, ready: authReady } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (authReady && user?.role !== "staff") router.replace("/login");
  }, [authReady, user, router]);

  const refresh = useCallback(async () => {
    const [r, res] = await Promise.all([adminListPricingRules(), listResources()]);
    setRules(r);
    setResources(res.results);
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh()
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [refresh]);

  async function submitDraft() {
    if (!draft) return;
    setSaving(true);
    setSaveError("");
    try {
      if (draft.id === null) {
        await adminCreatePricingRule({
          name: draft.name.trim(),
          description: draft.description.trim(),
          enabled: draft.enabled,
          priority: draft.priority,
          stackable: draft.stackable,
          rule_type: draft.rule_type,
          params: draft.params,
          applies_to_resource_id: null,
        });
      } else {
        await adminUpdatePricingRule(draft.id, {
          name: draft.name.trim(),
          description: draft.description.trim(),
          enabled: draft.enabled,
          priority: draft.priority,
          stackable: draft.stackable,
          rule_type: draft.rule_type,
          params: draft.params,
        });
      }
      setDraft(null);
      await refresh();
    } catch (err) {
      const msg =
        err && typeof err === "object" && "body" in err
          ? JSON.stringify((err as { body: unknown }).body)
          : "Couldn't save this rule — check the params shape.";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function removeRule(id: number) {
    if (!confirm("Delete this rule? It cannot be undone.")) return;
    try {
      await adminDeletePricingRule(id);
      await refresh();
    } catch {
      await refresh();
    }
  }

  async function toggleEnabled(rule: PricingRule) {
    await adminUpdatePricingRule(rule.id, { enabled: !rule.enabled });
    await refresh();
  }

  async function bumpPriority(rule: PricingRule, delta: number) {
    await adminUpdatePricingRule(rule.id, { priority: Math.max(0, rule.priority + delta) });
    await refresh();
  }

  if (!authReady) return <div className="pd-admin" />;
  if (user?.role !== "staff") return null;
  if (loading) {
    return (
      <div className="pd-admin">
        <div className="pd-empty">Loading pricing rules…</div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="pd-admin">
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load pricing rules. Refresh to try again.
        </div>
      </div>
    );
  }

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Pricing</div>
          <h1 className="pd-admin-title">Pricing rules</h1>
        </div>
        <div className="pd-admin-head-r">
          <button
            className="pd-btn pd-btn--primary pd-btn--sm"
            onClick={() => setDraft({ ...BLANK_DRAFT })}
          >
            New rule
          </button>
        </div>
      </header>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">
            {rules.length} rule{rules.length === 1 ? "" : "s"}
          </h2>
          <span className="pd-card-sub">Lower priority = applied first</span>
        </div>
        {rules.length === 0 ? (
          <div className="pd-empty">
            No pricing rules yet. Use “New rule” to add one — the booking
            page falls back to <span className="pd-mono">price_per_hour × hours</span>.
          </div>
        ) : (
          <div className="pd-table">
            <div
              className="pd-tr pd-tr--head"
              style={{ gridTemplateColumns: "1.6fr 1fr 0.6fr 0.6fr 0.6fr 1fr" }}
            >
              <div className="pd-th">Name</div>
              <div className="pd-th">Type</div>
              <div className="pd-th">Priority</div>
              <div className="pd-th">Stackable</div>
              <div className="pd-th">Enabled</div>
              <div className="pd-th">Actions</div>
            </div>
            {rules.map((r) => (
              <div
                key={r.id}
                className="pd-tr"
                style={{ gridTemplateColumns: "1.6fr 1fr 0.6fr 0.6fr 0.6fr 1fr" }}
              >
                <div className="pd-td pd-td-strong">{r.name}</div>
                <div className="pd-td pd-td-sub">{RULE_TYPE_SHORT[r.rule_type] ?? r.rule_type}</div>
                <div className="pd-td pd-mono" style={{ display: "flex", gap: 4 }}>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => bumpPriority(r, -10)}
                    aria-label="Decrease priority"
                  >
                    ↑
                  </button>
                  <span>{r.priority}</span>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => bumpPriority(r, +10)}
                    aria-label="Increase priority"
                  >
                    ↓
                  </button>
                </div>
                <div className="pd-td">
                  <span className="pd-chip pd-chip--ghost">{r.stackable ? "Yes" : "No"}</span>
                </div>
                <div className="pd-td">
                  <button
                    className="pd-chip pd-chip--ghost"
                    onClick={() => toggleEnabled(r)}
                    aria-label={`Toggle ${r.enabled ? "off" : "on"}`}
                  >
                    {r.enabled ? "On" : "Off"}
                  </button>
                </div>
                <div className="pd-td" style={{ display: "flex", gap: 6 }}>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => setDraft(ruleToDraft(r))}
                  >
                    Edit
                  </button>
                  <button
                    className="pd-btn pd-btn--ghost pd-btn--sm"
                    onClick={() => removeRule(r.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <QuoteSandbox resources={resources} />

      {draft && (
        <RuleForm
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
