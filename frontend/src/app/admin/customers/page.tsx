"use client";

// /admin/customers — paginated, debounced-search list of every customer
// known to the platform. Foundational for the retention surface; deeper
// detail lives on the row's /admin/customers/[id] page.
//
// v11c retention-scoring extension: a cohort filter chip toolbar with
// per-cohort counts, plus a "Send re-engagement to all visible" button
// that fires the bulk-send endpoint when a non-"all" cohort is active.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { CohortChip, COHORT_LABELS, COHORT_ORDER } from "@/components/admin/cohort-chip";
import { fmtDate, relTime } from "@/components/pd-ui";
import {
  adminBulkSendToCohort,
  adminListCustomers,
  type CohortCounts,
  type CustomerCohort,
  type CustomerSummary,
} from "@/lib/api";
import { useStaffSession } from "@/lib/staff-session";
import { useCurrentStore } from "@/lib/store-context";

const SEARCH_DEBOUNCE_MS = 300;
const EMPTY_COUNTS: CohortCounts = {
  new: 0,
  active: 0,
  at_risk: 0,
  dormant: 0,
  lost: 0,
};

interface PageState {
  loading: boolean;
  error: boolean;
  count: number;
  results: CustomerSummary[];
  cohortCounts: CohortCounts;
}

const EMPTY: PageState = {
  loading: true,
  error: false,
  count: 0,
  results: [],
  cohortCounts: EMPTY_COUNTS,
};

type CohortFilter = "all" | CustomerCohort;

export default function AdminCustomersPage() {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [page, setPage] = useState(1);
  const [cohortFilter, setCohortFilter] = useState<CohortFilter>("all");
  const [state, setState] = useState<PageState>(EMPTY);
  const [bulkSending, setBulkSending] = useState(false);
  const [bulkToast, setBulkToast] = useState("");

  const { user, ready: authReady } = useStaffSession();
  const router = useRouter();
  useEffect(() => {
    if (authReady && !user?.is_staff) router.replace("/staff/login");
  }, [authReady, user, router]);

  // v6 multi-location: refetch the customer list when the admin switches
  // store so we don't display rows scoped to the previous store.
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;

  // Debounce the search input.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedQ(q.trim()), SEARCH_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [q]);

  // Search / cohort changes reset pagination + clear any prior toast.
  useEffect(() => {
    setPage(1);
    setBulkToast("");
  }, [debouncedQ, cohortFilter]);

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: false }));
    adminListCustomers({
      q: debouncedQ || undefined,
      page,
      cohort: cohortFilter === "all" ? undefined : cohortFilter,
    })
      .then((data) => {
        if (cancelled) return;
        setState({
          loading: false,
          error: false,
          count: data.count,
          results: data.results,
          cohortCounts: data.cohort_counts ?? EMPTY_COUNTS,
        });
      })
      .catch(() => {
        if (!cancelled)
          setState({
            loading: false,
            error: true,
            count: 0,
            results: [],
            cohortCounts: EMPTY_COUNTS,
          });
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQ, page, storeSlug, cohortFilter]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(state.count / 20)), [state.count]);

  async function sendReEngagement() {
    if (cohortFilter === "all" || bulkSending) return;
    const label = COHORT_LABELS[cohortFilter];
    const confirmed = window.confirm(
      `Send the re-engagement message to all ${state.count} ${label} customers? ` +
        `Opted-out customers will be skipped automatically.`,
    );
    if (!confirmed) return;
    setBulkSending(true);
    setBulkToast("");
    try {
      const res = await adminBulkSendToCohort(cohortFilter, "re_engagement_60d");
      setBulkToast(`Sent to ${res.sent} customers, skipped ${res.skipped}.`);
    } catch {
      setBulkToast("Bulk send failed. Try again or check the logs.");
    } finally {
      setBulkSending(false);
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (!user?.is_staff) return null;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Customers</div>
          <h1 className="pd-admin-title">Everyone who&apos;s walked in</h1>
        </div>
        <div className="pd-admin-head-r">
          <label className="pd-search">
            <input
              placeholder="Search by name or phone…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
        </div>
      </header>

      {/* Cohort filter chips — v11c retention-scoring. */}
      <div
        className="pd-card-sub"
        data-testid="cohort-filter"
        style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0 16px" }}
      >
        <button
          type="button"
          className={`pd-chip ${cohortFilter === "all" ? "" : "pd-chip--ghost"}`}
          onClick={() => setCohortFilter("all")}
          data-cohort-button="all"
        >
          All ({state.count})
        </button>
        {COHORT_ORDER.map((c) => (
          <button
            key={c}
            type="button"
            className={`pd-chip ${cohortFilter === c ? "" : "pd-chip--ghost"}`}
            onClick={() => setCohortFilter(c)}
            data-cohort-button={c}
          >
            {COHORT_LABELS[c]} ({state.cohortCounts[c] ?? 0})
          </button>
        ))}
        {cohortFilter !== "all" && (
          <button
            type="button"
            className="pd-btn pd-btn--primary pd-btn--sm"
            onClick={sendReEngagement}
            disabled={bulkSending || state.count === 0}
            data-testid="cohort-bulk-send"
          >
            {bulkSending
              ? "Sending…"
              : `Send re-engagement to all ${state.count} visible`}
          </button>
        )}
        {bulkToast && (
          <span className="pd-card-sub" data-testid="cohort-bulk-toast">
            {bulkToast}
          </span>
        )}
      </div>

      <section className="pd-card">
        <div className="pd-card-head">
          <h2 className="pd-card-title">
            {state.count} customer{state.count === 1 ? "" : "s"}
          </h2>
          <span className="pd-card-sub">
            Page {page} of {totalPages}
          </span>
        </div>

        {state.loading && <div className="pd-empty">Loading customers…</div>}
        {state.error && (
          <div className="pd-error">
            <span className="pd-error-dot" />
            Couldn&apos;t load customers. Refresh to try again.
          </div>
        )}

        {!state.loading && !state.error && (
          <div className="pd-table">
            <div
              className="pd-tr pd-tr--head"
              style={{ gridTemplateColumns: "1.4fr 1.1fr 1fr 0.7fr 0.9fr 1.1fr" }}
            >
              <div className="pd-th">Name</div>
              <div className="pd-th">Phone</div>
              <div className="pd-th">Last visit</div>
              <div className="pd-th">Visits</div>
              <div className="pd-th">Cohort</div>
              <div className="pd-th">Tags</div>
            </div>
            {state.results.length === 0 && (
              <div className="pd-table-empty">No customers match this search.</div>
            )}
            {state.results.map((c) => (
              <Link
                key={c.id}
                className="pd-tr pd-tr--row"
                href={`/admin/customers/${c.id}`}
                style={{ display: "grid", gridTemplateColumns: "1.4fr 1.1fr 1fr 0.7fr 0.9fr 1.1fr" }}
              >
                <div className="pd-td pd-td-strong">{c.name || "(no name on file)"}</div>
                <div className="pd-td pd-mono">{c.phone}</div>
                <div className="pd-td pd-td-sub">
                  {c.last_visit_at ? relTime(c.last_visit_at) : "—"}
                  {c.last_visit_at && (
                    <div className="pd-td-sub pd-mono">{fmtDate(c.last_visit_at)}</div>
                  )}
                </div>
                <div className="pd-td pd-mono">{c.total_visits}</div>
                <div className="pd-td">
                  <CohortChip cohort={c.cohort} />
                </div>
                <div className="pd-td">
                  {c.tags.length === 0
                    ? "—"
                    : c.tags.map((t) => (
                        <span key={t} className="pd-chip pd-chip--ghost">
                          {t}
                        </span>
                      ))}
                </div>
              </Link>
            ))}
          </div>
        )}

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
    </div>
  );
}
