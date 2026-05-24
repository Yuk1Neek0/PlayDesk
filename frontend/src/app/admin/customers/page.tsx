"use client";

// /admin/customers — paginated, debounced-search list of every customer
// known to the platform. Foundational for the retention surface; deeper
// detail lives on the row's /admin/customers/[id] page.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { fmtDate, relTime } from "@/components/pd-ui";
import { adminListCustomers, type CustomerSummary } from "@/lib/api";
import { useStaffSession } from "@/lib/staff-session";
import { useCurrentStore } from "@/lib/store-context";

const SEARCH_DEBOUNCE_MS = 300;

interface PageState {
  loading: boolean;
  error: boolean;
  count: number;
  results: CustomerSummary[];
}

const EMPTY: PageState = { loading: true, error: false, count: 0, results: [] };

export default function AdminCustomersPage() {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [page, setPage] = useState(1);
  const [state, setState] = useState<PageState>(EMPTY);

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

  // A change to the search term resets pagination.
  useEffect(() => {
    setPage(1);
  }, [debouncedQ]);

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: false }));
    adminListCustomers({ q: debouncedQ || undefined, page })
      .then((data) => {
        if (cancelled) return;
        setState({ loading: false, error: false, count: data.count, results: data.results });
      })
      .catch(() => {
        if (!cancelled) setState({ loading: false, error: true, count: 0, results: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQ, page, storeSlug]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(state.count / 20)), [state.count]);

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
            <div className="pd-tr pd-tr--head">
              <div className="pd-th">Name</div>
              <div className="pd-th">Phone</div>
              <div className="pd-th">Last visit</div>
              <div className="pd-th">Total visits</div>
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
                style={{ display: "grid", gridTemplateColumns: "1.6fr 1.2fr 1.2fr 0.8fr 1.2fr" }}
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
