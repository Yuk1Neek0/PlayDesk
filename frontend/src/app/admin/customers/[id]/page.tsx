"use client";

// /admin/customers/[id] — profile card + visit history + notes log
// + "add note" form. The visits and notes embed in one request from the
// detail endpoint so this page is a single round-trip on load.

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import MembershipSection from "@/components/admin/membership-section";
import OutboundMessagesSection from "@/components/admin/outbound-messages-section";
import { fmtDate, fmtTime, relTime } from "@/components/pd-ui";
import {
  adminAddCustomerNote,
  adminGetCustomer,
  type CustomerDetail,
} from "@/lib/api";
import { useStaffSession } from "@/lib/staff-session";
import { useCurrentStore } from "@/lib/store-context";

interface State {
  loading: boolean;
  error: boolean;
  data: CustomerDetail | null;
}

const EMPTY: State = { loading: true, error: false, data: null };

export default function CustomerDetailPage() {
  const params = useParams<{ id: string }>();
  const idParam = params?.id;
  const customerId = idParam ? Number(idParam) : null;

  const [state, setState] = useState<State>(EMPTY);
  const [noteBody, setNoteBody] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteError, setNoteError] = useState("");

  const { user, ready: authReady } = useStaffSession();
  const router = useRouter();
  useEffect(() => {
    if (authReady && !user?.is_staff) router.replace("/staff/login");
  }, [authReady, user, router]);

  // v6 multi-location: refetch on store switch so a customer that doesn't
  // exist in the new store surfaces the standard error state.
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;

  useEffect(() => {
    if (customerId === null || Number.isNaN(customerId)) return;
    let cancelled = false;
    setState({ loading: true, error: false, data: null });
    adminGetCustomer(customerId)
      .then((data) => {
        if (!cancelled) setState({ loading: false, error: false, data });
      })
      .catch(() => {
        if (!cancelled) setState({ loading: false, error: true, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [customerId, storeSlug]);

  async function submitNote() {
    if (customerId === null || !noteBody.trim() || noteSaving) return;
    setNoteSaving(true);
    setNoteError("");
    try {
      const note = await adminAddCustomerNote(customerId, noteBody.trim());
      setNoteBody("");
      setState((s) =>
        s.data ? { ...s, data: { ...s.data, notes: [note, ...s.data.notes] } } : s,
      );
    } catch {
      setNoteError("Couldn't save the note. Try again.");
    } finally {
      setNoteSaving(false);
    }
  }

  if (!authReady) return <div className="pd-admin" />;
  if (!user?.is_staff) return null;
  if (state.loading) return <div className="pd-admin"><div className="pd-empty">Loading…</div></div>;
  if (state.error || !state.data) {
    return (
      <div className="pd-admin">
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t load this customer.
        </div>
      </div>
    );
  }

  const c = state.data;

  return (
    <div className="pd-admin">
      <header className="pd-admin-head">
        <div>
          <Link className="pd-link" href="/admin/customers">
            ← All customers
          </Link>
          <h1 className="pd-admin-title">{c.name || "(no name on file)"}</h1>
          <div className="pd-mono pd-card-sub" style={{ marginTop: 4 }}>
            {c.phone}
            {c.email ? ` · ${c.email}` : ""}
          </div>
        </div>
        <div className="pd-admin-head-r">
          <div className="pd-stat" style={{ minWidth: 160 }}>
            <div className="pd-stat-label">Total visits</div>
            <div className="pd-stat-value pd-mono">{c.total_visits}</div>
          </div>
        </div>
      </header>

      <div className="pd-admin-grid">
        {/* Visit history */}
        <section className="pd-card">
          <div className="pd-card-head">
            <h2 className="pd-card-title">Visit history</h2>
            <span className="pd-card-sub">{c.visits.length} most recent</span>
          </div>
          {c.visits.length === 0 ? (
            <div className="pd-empty">No visits on record yet.</div>
          ) : (
            <div className="pd-table">
              <div
                className="pd-tr pd-tr--head"
                style={{ gridTemplateColumns: "1.3fr 1fr 0.9fr 0.8fr" }}
              >
                <div className="pd-th">When</div>
                <div className="pd-th">Resource</div>
                <div className="pd-th">Status</div>
                <div className="pd-th">Source</div>
              </div>
              {c.visits.map((v) => (
                <div
                  key={v.id}
                  className="pd-tr"
                  style={{ gridTemplateColumns: "1.3fr 1fr 0.9fr 0.8fr" }}
                >
                  <div className="pd-td">
                    <div className="pd-td-strong">{fmtDate(v.start_time)}</div>
                    <div className="pd-td-sub pd-mono">
                      {fmtTime(v.start_time)}–{fmtTime(v.end_time)}
                    </div>
                  </div>
                  <div className="pd-td pd-td-strong">{v.resource_name}</div>
                  <div className="pd-td">
                    <span className="pd-chip pd-chip--ghost">{v.status}</span>
                  </div>
                  <div className="pd-td">
                    <span className="pd-chip pd-chip--ghost">{v.source}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Notes log */}
        <section className="pd-card">
          <div className="pd-card-head">
            <h2 className="pd-card-title">Notes</h2>
            <span className="pd-card-sub">{c.notes.length}</span>
          </div>

          <div className="pd-preview-body">
            <div className="pd-field">
              <textarea
                className="pd-input"
                placeholder="Add a note about this customer…"
                rows={3}
                value={noteBody}
                onChange={(e) => setNoteBody(e.target.value)}
                disabled={noteSaving}
              />
              {noteError && (
                <div className="pd-error">
                  <span className="pd-error-dot" /> {noteError}
                </div>
              )}
              <button
                className="pd-btn pd-btn--primary pd-btn--sm"
                disabled={!noteBody.trim() || noteSaving}
                onClick={submitNote}
              >
                {noteSaving ? "Saving…" : "Add note"}
              </button>
            </div>

            {c.notes.length === 0 ? (
              <div className="pd-empty">No notes yet.</div>
            ) : (
              c.notes.map((n) => (
                <div key={n.id} className="pd-pmsg pd-pmsg--ai" style={{ maxWidth: "100%" }}>
                  <div className="pd-pmsg-text">{n.body}</div>
                  <div className="pd-card-sub pd-mono" style={{ marginTop: 6 }}>
                    {n.author_username ?? "anonymous"} · {relTime(n.created_at)}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Outbound messages — confirmations, reminders, no-show recovery, ... */}
        <OutboundMessagesSection customerId={c.id} />
      </div>

      {/* Membership card — points balance, tier, ledger, adjust + redeem */}
      <MembershipSection customerId={c.id} />
    </div>
  );
}
