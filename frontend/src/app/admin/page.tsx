"use client";

// Staff dashboard — UI ported from the Claude Design handoff, wired to the
// live admin endpoints: bookings and conversations load from the REST client,
// the selected conversation's transcript is fetched on demand, and the
// bookings table polls so new bookings surface without a manual refresh.
// This completes task #22.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useStaffSession } from "@/lib/staff-session";
import { useCurrentStore } from "@/lib/store-context";
import { BusinessDashboardStrip } from "@/components/admin/business-dashboard-strip";
import { CheckInBadge } from "@/components/admin/checkin-badge";
import {
  Icon,
  ResourceIcon,
  SourceBadge,
  StatusBadge,
  fmtDate,
  fmtTime,
  relTime,
} from "@/components/pd-ui";
import {
  adminCheckInBooking,
  adminListBookings,
  adminListConversations,
  adminUndoCheckInBooking,
  getConversation,
  listResources,
  type Booking,
  type Conversation,
  type ConversationDetail,
  type Resource,
} from "@/lib/api";

type LoadState = "loading" | "ready" | "error";

// The bookings table refetches on this cadence so new bookings appear live.
const POLL_MS = 12_000;

interface PreviewState {
  loading: boolean;
  error: boolean;
  data: ConversationDetail | null;
}

export default function AdminPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [resourceById, setResourceById] = useState<Record<string, Resource>>({});
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const [updatedAgo, setUpdatedAgo] = useState(0);
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("all");
  const [checkInFilter, setCheckInFilter] = useState<"all" | "yes" | "no">("all");
  const [search, setSearch] = useState("");
  const [channelFilter, setChannelFilter] = useState<
    "all" | "web_chat" | "sms" | "whatsapp" | "phone" | "manual_staff"
  >("all");
  const [selectedConv, setSelectedConv] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewState>({
    loading: false,
    error: false,
    data: null,
  });

  // Staff-only route guard: send anyone not signed in as staff to /login.
  const { user, ready: authReady } = useStaffSession();
  const router = useRouter();
  useEffect(() => {
    if (authReady && !user?.is_staff) router.replace("/staff/login");
  }, [authReady, user, router]);

  // Current store from the v6 multi-location switcher. `current?.slug` is
  // in every fetch effect's dep array so a store switch triggers refetch.
  const { current } = useCurrentStore();
  const storeSlug = current?.slug ?? null;

  // Booking ids seen on the last load — used to flag freshly arrived rows.
  const bookingIdsRef = useRef<Set<number>>(new Set());

  // Initial load: resources, bookings, and conversations together.
  // Re-runs when the active store changes so the dashboard reflects the
  // new store's data instead of mixing rows across stores.
  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    bookingIdsRef.current = new Set();
    Promise.all([listResources(), adminListBookings(), adminListConversations()])
      .then(([res, bk, cv]) => {
        if (cancelled) return;
        setResourceById(Object.fromEntries(res.results.map((r) => [r.id, r] as const)));
        setBookings(bk.results);
        bookingIdsRef.current = new Set(bk.results.map((b) => b.id));
        setConversations(cv.results);
        setSelectedConv(cv.results[0]?.id ?? null);
        setLoadState("ready");
      })
      .catch(() => {
        if (!cancelled) setLoadState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [storeSlug]);

  // Live updates: tick the "updated Xs ago" label and poll the bookings list.
  // Re-creating the poll on store-switch ensures the polled list scopes to
  // the new store via the X-PD-Store-Slug header.
  useEffect(() => {
    const ticker = setInterval(() => setUpdatedAgo((s) => s + 5), 5_000);
    const poll = setInterval(() => {
      adminListBookings()
        .then((bk) => {
          const fresh = bk.results
            .filter((b) => !bookingIdsRef.current.has(b.id))
            .map((b) => b.id);
          bookingIdsRef.current = new Set(bk.results.map((b) => b.id));
          setBookings(bk.results);
          setUpdatedAgo(0);
          if (fresh.length > 0) {
            setNewIds(new Set(fresh));
            setTimeout(() => setNewIds(new Set()), 3_500);
          }
        })
        .catch(() => {
          /* keep the last good data; the next poll will retry */
        });
    }, POLL_MS);
    return () => {
      clearInterval(ticker);
      clearInterval(poll);
    };
  }, [storeSlug]);

  // Re-fetch conversations whenever the channel filter changes. Skipped
  // on first mount because the initial Promise.all already loaded them.
  const didMountConvRef = useRef(false);
  useEffect(() => {
    if (!didMountConvRef.current) {
      didMountConvRef.current = true;
      return;
    }
    let cancelled = false;
    const params = channelFilter === "all" ? undefined : { channel: channelFilter };
    adminListConversations(params)
      .then((cv) => {
        if (cancelled) return;
        setConversations(cv.results);
        // If the previously-selected conversation was filtered out, drop it.
        if (cv.results.every((c) => c.id !== selectedConv)) {
          setSelectedConv(cv.results[0]?.id ?? null);
        }
      })
      .catch(() => {
        /* keep last good data; user can re-try */
      });
    return () => {
      cancelled = true;
    };
    // selectedConv intentionally omitted — we only want re-fetch on filter change.
    // storeSlug included so a store switch refetches with the new scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelFilter, storeSlug]);

  // Load the selected conversation's transcript for the preview panel.
  useEffect(() => {
    if (selectedConv === null) return;
    let cancelled = false;
    setPreview({ loading: true, error: false, data: null });
    getConversation(selectedConv)
      .then((data) => {
        if (!cancelled) setPreview({ loading: false, error: false, data });
      })
      .catch(() => {
        if (!cancelled) setPreview({ loading: false, error: true, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedConv]);

  const filtered = useMemo(
    () =>
      bookings.filter((b) => {
        if (statusFilter !== "all" && b.status !== statusFilter) return false;
        if (dateFilter !== "all") {
          const d = b.start_time.slice(0, 10);
          if (dateFilter === "today" && d !== "2026-05-22") return false;
          if (dateFilter === "tomorrow" && d !== "2026-05-23") return false;
        }
        if (checkInFilter !== "all") {
          // v10b checkin: client-side filter — the backend honours
          // `?checked_in=yes|no` too, but filtering in-memory keeps
          // the existing single-fetch + poll cadence.
          const bb = b as Booking & { checked_in_at?: string | null };
          // BookingStatus from the OpenAPI contract pre-dates the
          // CHECKED_IN value — compare as string until the contract
          // regen lands.
          const checkedIn =
            (bb.status as string) === "checked_in" || Boolean(bb.checked_in_at);
          if (checkInFilter === "yes" && !checkedIn) return false;
          if (checkInFilter === "no" && checkedIn) return false;
        }
        if (search) {
          const q = search.toLowerCase();
          const hit =
            b.customer_name.toLowerCase().includes(q) ||
            (resourceById[b.resource_id]?.name ?? "").toLowerCase().includes(q) ||
            b.customer_phone.includes(q) ||
            String(b.id).includes(q);
          if (!hit) return false;
        }
        return true;
      }),
    [bookings, statusFilter, dateFilter, checkInFilter, search, resourceById],
  );

  const stats = useMemo(() => {
    const today = bookings.filter((b) => b.start_time.startsWith("2026-05-22"));
    return {
      today: today.length,
      confirmed: today.filter((b) => b.status === "confirmed").length,
      pending_payment: bookings.filter((b) => b.status === "pending_payment").length,
      active_chats: conversations.filter((c) => c.status === "active").length,
    };
  }, [bookings, conversations]);

  const activeConv = conversations.find((c) => c.id === selectedConv);

  // Hold rendering until the persisted session is resolved, then render
  // nothing while a non-staff visitor is being redirected to /login.
  if (!authReady) return <div className="pd-admin" />;
  if (!user?.is_staff) return null;

  return (
    <div className="pd-admin">
      <BusinessDashboardStrip />
      <header className="pd-admin-head">
        <div>
          <div className="pd-eyebrow">Staff dashboard</div>
          <h1 className="pd-admin-title">Tonight at PlayDesk</h1>
        </div>
        <div className="pd-admin-head-r">
          <span className="pd-live">
            <span className="pd-pulse" /> Live · updated{" "}
            {updatedAgo === 0 ? "just now" : `${updatedAgo}s ago`}
          </span>
          <div className="pd-admin-user">
            <div className="pd-avatar pd-avatar--user">YS</div>
            <div className="pd-admin-user-meta">
              <div>Yuki S.</div>
              <div className="pd-admin-user-role">Front desk · Toronto</div>
            </div>
          </div>
        </div>
      </header>

      {loadState === "loading" && <div className="pd-empty">Loading the dashboard…</div>}
      {loadState === "error" && (
        <div className="pd-error">
          <span className="pd-error-dot" />
          Couldn&apos;t reach the backend. Refresh to try again.
        </div>
      )}

      {loadState === "ready" && (
        <>
          <div className="pd-stat-grid">
            <StatTile label="Today's bookings" value={stats.today} />
            <StatTile label="Confirmed" value={stats.confirmed} accent="ok" />
            <StatTile label="Pending payment" value={stats.pending_payment} accent="warn" />
            <StatTile label="Active AI chats" value={stats.active_chats} accent="info" />
          </div>

          <div className="pd-admin-grid">
            {/* Live conversations panel */}
            <section className="pd-card">
              <div className="pd-card-head">
                <h2 className="pd-card-title">Live conversations</h2>
                <span className="pd-card-sub">
                  {conversations.filter((c) => c.status === "active").length} active
                </span>
              </div>
              <div className="pd-seg pd-seg--sm" style={{ marginBottom: 12 }}>
                {(
                  [
                    ["all", "All"],
                    ["web_chat", "Web"],
                    ["sms", "SMS"],
                    ["whatsapp", "WhatsApp"],
                    ["phone", "Phone"],
                    ["manual_staff", "Staff"],
                  ] as const
                ).map(([k, label]) => (
                  <button
                    key={k}
                    className={`pd-seg-item ${channelFilter === k ? "is-active" : ""}`}
                    onClick={() => setChannelFilter(k)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="pd-conv-list">
                {conversations.length === 0 && (
                  <div className="pd-empty">No conversations yet.</div>
                )}
                {conversations.map((c) => (
                  <button
                    key={c.id}
                    className={`pd-conv ${c.id === selectedConv ? "is-active" : ""} ${c.status === "closed" ? "is-closed" : ""}`}
                    onClick={() => setSelectedConv(c.id)}
                  >
                    <div className="pd-conv-l">
                      <div className={`pd-conv-state pd-conv-state--${c.status}`} />
                      <div>
                        <div className="pd-conv-id">{c.customer_identifier}</div>
                        <div className="pd-conv-last">
                          {c.status === "active" ? "Active session" : "Closed"}
                        </div>
                      </div>
                    </div>
                    <div className="pd-conv-r">
                      <div className="pd-conv-time">{relTime(c.started_at)}</div>
                    </div>
                  </button>
                ))}
              </div>
            </section>

            {/* Selected-conversation transcript */}
            <section className="pd-card">
              <div className="pd-card-head">
                <h2 className="pd-card-title">
                  {selectedConv !== null ? `Conversation #${selectedConv}` : "Conversation"}
                </h2>
                <span className="pd-card-sub">{activeConv?.customer_identifier}</span>
              </div>
              <ConversationPreview preview={preview} hasSelection={selectedConv !== null} />
              <div className="pd-preview-foot">
                <button className="pd-btn pd-btn--ghost pd-btn--sm">Take over</button>
                <button className="pd-btn pd-btn--ghost pd-btn--sm">Mark resolved</button>
              </div>
            </section>
          </div>

          {/* Bookings table */}
          <section className="pd-card">
            <div className="pd-card-head pd-card-head--filters">
              <div>
                <h2 className="pd-card-title">All bookings</h2>
                <span className="pd-card-sub">
                  Newest first · {filtered.length} of {bookings.length}
                </span>
              </div>
              <div className="pd-filters">
                <label className="pd-search">
                  <Icon.search size={14} />
                  <input
                    placeholder="Search name, phone, #id…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
                <FilterChips
                  label="Status"
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    ["all", "All"],
                    ["confirmed", "Confirmed"],
                    ["pending_payment", "Pending payment"],
                    ["pending", "Pending"],
                    ["cancelled", "Cancelled"],
                  ]}
                />
                <FilterChips
                  label="Date"
                  value={dateFilter}
                  onChange={setDateFilter}
                  options={[
                    ["all", "Any"],
                    ["today", "Today"],
                    ["tomorrow", "Tomorrow"],
                  ]}
                />
                <FilterChips
                  label="Check-in"
                  value={checkInFilter}
                  onChange={(v) => setCheckInFilter(v as "all" | "yes" | "no")}
                  options={[
                    ["all", "All"],
                    ["no", "Not yet"],
                    ["yes", "Checked in"],
                  ]}
                />
              </div>
            </div>

            <div className="pd-table">
              <div className="pd-tr pd-tr--head">
                <div className="pd-th">ID</div>
                <div className="pd-th">Customer</div>
                <div className="pd-th">Resource</div>
                <div className="pd-th">When</div>
                <div className="pd-th">Status</div>
                <div className="pd-th">Check-in</div>
                <div className="pd-th">Source</div>
                <div className="pd-th pd-th--right">Created</div>
              </div>
              {filtered.length === 0 && (
                <div className="pd-table-empty">No bookings match these filters.</div>
              )}
              {filtered.map((b) => {
                const r = resourceById[b.resource_id];
                return (
                  <div key={b.id} className={`pd-tr ${newIds.has(b.id) ? "is-new" : ""}`}>
                    <div className="pd-td pd-mono pd-td-id">#{b.id}</div>
                    <div className="pd-td">
                      <div className="pd-td-strong">{b.customer_name}</div>
                      <div className="pd-td-sub pd-mono">{b.customer_phone}</div>
                    </div>
                    <div className="pd-td">
                      <div className="pd-td-resource">
                        <span className="pd-td-rico">
                          <ResourceIcon type={r?.type} size={14} />
                        </span>
                        {r?.name ?? `Resource #${b.resource_id}`}
                      </div>
                    </div>
                    <div className="pd-td">
                      <div className="pd-td-strong">{fmtDate(b.start_time)}</div>
                      <div className="pd-td-sub pd-mono">
                        {fmtTime(b.start_time)}–{fmtTime(b.end_time)}
                      </div>
                    </div>
                    <div className="pd-td">
                      <StatusBadge status={b.status} />
                    </div>
                    <div className="pd-td">
                      <CheckInCell
                        booking={b}
                        onUpdated={(updated) =>
                          setBookings((bs) =>
                            bs.map((row) => (row.id === updated.id ? updated : row)),
                          )
                        }
                      />
                    </div>
                    <div className="pd-td">
                      <SourceBadge source={b.source} />
                    </div>
                    <div className="pd-td pd-td--right pd-td-sub">
                      <BookingTotal booking={b} />
                      <div>{relTime(b.created_at)}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function ConversationPreview({
  preview,
  hasSelection,
}: {
  preview: PreviewState;
  hasSelection: boolean;
}) {
  if (!hasSelection) {
    return <div className="pd-empty">Select a conversation to see its transcript.</div>;
  }
  if (preview.loading) {
    return <div className="pd-empty">Loading transcript…</div>;
  }
  if (preview.error || !preview.data) {
    return (
      <div className="pd-error">
        <span className="pd-error-dot" />
        Couldn&apos;t load this conversation.
      </div>
    );
  }
  const messages = preview.data.messages ?? [];
  if (messages.length === 0) {
    return <div className="pd-empty">No messages in this conversation yet.</div>;
  }
  return (
    <div className="pd-preview-body">
      {messages.map((m) => (
        <PreviewMsg
          key={m.id}
          role={m.role === "user" ? "user" : "ai"}
          text={m.content}
          tool={m.role === "tool" ? "tool result" : undefined}
        />
      ))}
    </div>
  );
}

function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "ok" | "warn" | "info";
}) {
  return (
    <div className={`pd-stat ${accent ? `pd-stat--${accent}` : ""}`}>
      <div className="pd-stat-label">{label}</div>
      <div className="pd-stat-value pd-mono">{value}</div>
    </div>
  );
}

function FilterChips({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  return (
    <div className="pd-filter">
      <span className="pd-filter-label">{label}</span>
      <div className="pd-seg pd-seg--sm">
        {options.map(([k, l]) => (
          <button
            key={k}
            className={`pd-seg-item ${value === k ? "is-active" : ""}`}
            onClick={() => onChange(k)}
          >
            {l}
          </button>
        ))}
      </div>
    </div>
  );
}

function PreviewMsg({
  role,
  text,
  tool,
}: {
  role: "user" | "ai";
  text: string;
  tool?: string;
}) {
  return (
    <div className={`pd-pmsg pd-pmsg--${role}`}>
      {tool && <span className="pd-pmsg-tool">{tool}</span>}
      <div className="pd-pmsg-text">{text}</div>
    </div>
  );
}

// v10b checkin — badge + inline manual check-in / undo button. Confirmed
// bookings show "Manual check-in", checked-in bookings show "Undo".
// Buttons POST through `adminCheckInBooking` / `adminUndoCheckInBooking`
// and bubble the updated row up so the table re-renders without a poll.
function CheckInCell({
  booking,
  onUpdated,
}: {
  booking: Booking;
  onUpdated: (b: Booking) => void;
}) {
  const [busy, setBusy] = useState(false);
  const b = booking as Booking & { checked_in_at?: string | null };
  async function manualCheckIn() {
    if (busy) return;
    setBusy(true);
    try {
      const updated = await adminCheckInBooking(booking.id);
      onUpdated(updated);
    } catch {
      /* swallow — next poll surfaces server state */
    } finally {
      setBusy(false);
    }
  }
  async function undoCheckIn() {
    if (busy) return;
    setBusy(true);
    try {
      const updated = await adminUndoCheckInBooking(booking.id);
      onUpdated(updated);
    } catch {
      /* swallow — next poll surfaces server state */
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="pd-td-checkin">
      <CheckInBadge checkedInAt={b.checked_in_at ?? null} status={b.status} />
      {b.status === "confirmed" && (
        <button
          className="pd-btn pd-btn--ghost pd-btn--sm"
          onClick={manualCheckIn}
          disabled={busy}
          data-testid={`manual-checkin-${booking.id}`}
        >
          Check in
        </button>
      )}
      {(b.status as string) === "checked_in" && (
        <button
          className="pd-btn pd-btn--ghost pd-btn--sm"
          onClick={undoCheckIn}
          disabled={busy}
          data-testid={`undo-checkin-${booking.id}`}
        >
          Undo
        </button>
      )}
    </div>
  );
}

// v8 pricing-rules — render the frozen total + rule-snapshot popover for
// a booking row. The total_amount / rule_snapshot fields aren't in the
// shared OpenAPI Booking type yet (the contract regen is gated on
// another epic landing); cast to a narrow shape locally so the admin
// table still picks them up.
function BookingTotal({ booking }: { booking: Booking }) {
  const b = booking as Booking & {
    total_amount?: string | null;
    rule_snapshot?: { label: string; amount: string; rule_id: number | null }[];
  };
  if (!b.total_amount) return null;
  const snap = b.rule_snapshot ?? [];
  const hasRules = snap.length > 1; // first row is "Base"
  return (
    <span
      title={
        hasRules
          ? snap.map((li) => `${li.label}: $${li.amount}`).join(" · ")
          : `Base $${b.total_amount}`
      }
      style={{ display: "inline-block", marginRight: 8 }}
    >
      <span className="pd-mono">${b.total_amount}</span>
      {hasRules && <span className="pd-chip pd-chip--ghost" style={{ marginLeft: 4 }}>{snap.length - 1} rules</span>}
    </span>
  );
}
