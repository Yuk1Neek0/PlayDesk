"use client";

// Staff dashboard — stat tiles, live conversations + preview, and a filtered
// bookings table that streams in a new row. Ported from the Claude Design
// handoff (playdeck/project/src/admin.jsx). Runs on the prototype's mock
// data; wiring to the real admin endpoints is the remaining work of task #22.

import { useEffect, useMemo, useState } from "react";

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
  BOOKINGS,
  CONVERSATIONS,
  RESOURCES,
  type Booking,
  type Resource,
} from "@/lib/pd-data";

export default function AdminPage() {
  const resourceById = useMemo<Record<string, Resource>>(
    () => Object.fromEntries(RESOURCES.map((r) => [r.id, r] as const)),
    [],
  );

  const [bookings, setBookings] = useState<Booking[]>(BOOKINGS);
  const [newRowId, setNewRowId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [updatedAgo, setUpdatedAgo] = useState(0);
  const [selectedConv, setSelectedConv] = useState(CONVERSATIONS[0]?.id);

  // "Updated just now" ticks every 8s; a new booking streams in after 6s.
  useEffect(() => {
    const tick = setInterval(() => setUpdatedAgo((s) => s + 8), 8000);
    const newBooking = setTimeout(() => {
      const id = 4113 + Math.floor(Math.random() * 80);
      setBookings((bs) => [
        {
          id,
          resource_id: 4,
          conversation_id: 91,
          customer_name: "Wei Lin",
          customer_phone: "+86 137 4421 0988",
          start_time: "2026-05-22T21:00:00+08:00",
          end_time: "2026-05-22T23:00:00+08:00",
          status: "pending_payment",
          source: "agent",
          created_at: new Date().toISOString(),
        },
        ...bs,
      ]);
      setNewRowId(id);
      setUpdatedAgo(0);
      setTimeout(() => setNewRowId(null), 3500);
    }, 6000);
    return () => {
      clearInterval(tick);
      clearTimeout(newBooking);
    };
  }, []);

  const filtered = useMemo(
    () =>
      bookings.filter((b) => {
        if (statusFilter !== "all" && b.status !== statusFilter) return false;
        if (dateFilter !== "all") {
          const d = b.start_time.slice(0, 10);
          if (dateFilter === "today" && d !== "2026-05-22") return false;
          if (dateFilter === "tomorrow" && d !== "2026-05-23") return false;
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
    [bookings, statusFilter, dateFilter, search, resourceById],
  );

  const stats = useMemo(() => {
    const today = bookings.filter((b) => b.start_time.startsWith("2026-05-22"));
    return {
      today: today.length,
      confirmed: today.filter((b) => b.status === "confirmed").length,
      pending_payment: bookings.filter((b) => b.status === "pending_payment").length,
      active_chats: CONVERSATIONS.filter((c) => c.status === "active").length,
    };
  }, [bookings]);

  const activeConv = CONVERSATIONS.find((c) => c.id === selectedConv);

  return (
    <div className="pd-admin">
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
              <div className="pd-admin-user-role">Front desk · 工大店</div>
            </div>
          </div>
        </div>
      </header>

      <div className="pd-stat-grid">
        <StatTile label="Today's bookings" value={stats.today} delta="+3" />
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
              {CONVERSATIONS.filter((c) => c.status === "active").length} active
            </span>
          </div>
          <div className="pd-conv-list">
            {CONVERSATIONS.map((c) => (
              <button
                key={c.id}
                className={`pd-conv ${c.id === selectedConv ? "is-active" : ""} ${c.status === "closed" ? "is-closed" : ""}`}
                onClick={() => setSelectedConv(c.id)}
              >
                <div className="pd-conv-l">
                  <div className={`pd-conv-state pd-conv-state--${c.status}`} />
                  <div>
                    <div className="pd-conv-id">{c.customer_identifier}</div>
                    <div className="pd-conv-last">{c.last}</div>
                  </div>
                </div>
                <div className="pd-conv-r">
                  <div className="pd-conv-msgs">
                    <span className="pd-mono">{c.messages}</span> msg
                  </div>
                  <div className="pd-conv-time">{relTime(c.started_at)}</div>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Selected-conversation preview */}
        <section className="pd-card">
          <div className="pd-card-head">
            <h2 className="pd-card-title">Conversation #{selectedConv}</h2>
            <span className="pd-card-sub">{activeConv?.customer_identifier}</span>
          </div>
          <div className="pd-preview-body">
            <PreviewMsg role="user" text="Is the PS5 free at 8 tonight for 2 of us?" />
            <PreviewMsg
              role="ai"
              tool="check_availability · ok"
              text="Yes — PS5 Station · A is free 20:00–23:00 tonight. Want me to book 2 hours? ¥116 total."
            />
            <PreviewMsg role="user" text="Yes please, name's Alice." />
            <PreviewMsg
              role="ai"
              tool="create_booking · #4112"
              text="Booked. Payment link sent to your number — you'll get an SMS in a moment."
            />
            <div className="pd-preview-pin">
              <span className="pd-pulse" /> Customer is typing…
            </div>
          </div>
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
          </div>
        </div>

        <div className="pd-table">
          <div className="pd-tr pd-tr--head">
            <div className="pd-th">ID</div>
            <div className="pd-th">Customer</div>
            <div className="pd-th">Resource</div>
            <div className="pd-th">When</div>
            <div className="pd-th">Status</div>
            <div className="pd-th">Source</div>
            <div className="pd-th pd-th--right">Created</div>
          </div>
          {filtered.length === 0 && (
            <div className="pd-table-empty">No bookings match these filters.</div>
          )}
          {filtered.map((b) => {
            const r = resourceById[b.resource_id];
            return (
              <div key={b.id} className={`pd-tr ${b.id === newRowId ? "is-new" : ""}`}>
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
                    {r?.name}
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
                  <SourceBadge source={b.source} />
                </div>
                <div className="pd-td pd-td--right pd-td-sub">{relTime(b.created_at)}</div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatTile({
  label,
  value,
  delta,
  accent,
}: {
  label: string;
  value: number;
  delta?: string;
  accent?: "ok" | "warn" | "info";
}) {
  return (
    <div className={`pd-stat ${accent ? `pd-stat--${accent}` : ""}`}>
      <div className="pd-stat-label">{label}</div>
      <div className="pd-stat-value pd-mono">{value}</div>
      {delta && <div className="pd-stat-delta">{delta} vs. yesterday</div>}
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
