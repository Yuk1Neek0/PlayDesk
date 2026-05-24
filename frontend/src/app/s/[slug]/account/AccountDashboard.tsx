"use client";

// Customer-portal dashboard at /s/[slug]/account.
//
// Four tabs:
//   - Upcoming   — GET /api/me/bookings/?status=upcoming + Reschedule/Cancel
//   - History    — GET /api/me/bookings/?status=past, paginated
//   - Loyalty    — GET /api/me/membership/ + POST /api/me/redeem/
//   - Profile    — GET /api/me/ + PATCH name + Logout
//
// Tabs are lazy-loaded (only the active tab fires its data fetch) to
// keep first paint snappy on mobile. The active tab is reflected in the
// URL via `?tab=...` so the browser back button works as expected.
//
// First-time customers (name === "") see a one-time prompt to set a
// display name before the dashboard renders.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Icon } from "@/components/pd-ui";
import { ApiError } from "@/lib/api";
import { customerFetch } from "@/lib/customer-fetch";
import type { StoreBrand } from "@/lib/store-brand";

interface SessionCustomer {
  id: number;
  name: string;
  phone: string;
  store_slug: string;
}

interface BookingResource {
  id: number;
  name: string;
  type: string;
}

interface MyBooking {
  id: number;
  start_at: string;
  end_at: string;
  status: string;
  resource: BookingResource;
}

interface BookingsPage {
  results: MyBooking[];
  total: number;
  has_more: boolean;
}

interface MembershipPayload {
  customer_id: number;
  balance: number;
  lifetime_earned: number;
  tier: { id: number; name: string; perks_text: string } | null;
  next_tier: { id: number; name: string; min_lifetime_points: number } | null;
  points_to_next_tier: number | null;
  recent_transactions: {
    id: number;
    delta: number;
    source: string;
    reference: string;
    balance_after: number;
    created_at: string;
  }[];
  available_rewards: { id: number; name: string; cost_points: number; description: string }[];
}

type TabKey = "upcoming" | "history" | "loyalty" | "profile";

const TABS: { key: TabKey; label: string }[] = [
  { key: "upcoming", label: "Upcoming" },
  { key: "history", label: "History" },
  { key: "loyalty", label: "Loyalty" },
  { key: "profile", label: "Profile" },
];

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface DashboardProps {
  brand: StoreBrand;
  storeSlug: string;
  initialCustomer: SessionCustomer;
}

export default function AccountDashboard({ brand, storeSlug, initialCustomer }: DashboardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") as TabKey) || "upcoming";
  const [tab, setTab] = useState<TabKey>(initialTab);
  const [customer, setCustomer] = useState<SessionCustomer>(initialCustomer);
  const [nameModalOpen, setNameModalOpen] = useState(initialCustomer.name === "");

  // Switch URL `?tab=...` when the tab changes — browser back works.
  const onSelectTab = useCallback(
    (next: TabKey) => {
      setTab(next);
      const sp = new URLSearchParams(searchParams.toString());
      sp.set("tab", next);
      router.replace(`/s/${storeSlug}/account?${sp.toString()}`);
    },
    [router, searchParams, storeSlug],
  );

  const wrapperStyle: React.CSSProperties | undefined = brand.accent
    ? ({ "--pd-accent": brand.accent, "--accent": brand.accent } as React.CSSProperties)
    : undefined;

  return (
    <div className="pd-page pd-page--booking" style={wrapperStyle}>
      <header className="pd-page-head">
        <div className="pd-brand-logo">
          {brand.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="pd-brand-logo-img" src={brand.logo_url} alt={brand.name} />
          ) : (
            <span className="pd-brand-mark" aria-hidden>
              <Icon.logo size={28} />
            </span>
          )}
        </div>
        <div className="pd-eyebrow">My account</div>
        <h1 className="pd-page-title">Hello, {customer.name || "there"}.</h1>
      </header>

      <div className="pd-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`pd-tab ${tab === t.key ? "is-active" : ""}`}
            onClick={() => onSelectTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {nameModalOpen && (
        <NamePrompt
          storeSlug={storeSlug}
          onDone={(name) => {
            setCustomer({ ...customer, name });
            setNameModalOpen(false);
          }}
        />
      )}

      {tab === "upcoming" && <UpcomingTab storeSlug={storeSlug} />}
      {tab === "history" && <HistoryTab storeSlug={storeSlug} />}
      {tab === "loyalty" && <LoyaltyTab storeSlug={storeSlug} />}
      {tab === "profile" && (
        <ProfileTab
          storeSlug={storeSlug}
          customer={customer}
          onCustomerChange={setCustomer}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// First-time name prompt
// ---------------------------------------------------------------------------

function NamePrompt({
  storeSlug,
  onDone,
}: {
  storeSlug: string;
  onDone: (name: string) => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!value.trim()) return;
    setBusy(true);
    try {
      await customerFetch<{ name: string }>(storeSlug, "/api/me/", {
        method: "PATCH",
        body: JSON.stringify({ name: value.trim() }),
      });
      onDone(value.trim());
    } catch {
      // Stay open on error — the dashboard is unusable without a name.
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="pd-step is-active" aria-label="Set your name">
      <div className="pd-step-body">
        <h2 className="pd-step-title">What should we call you?</h2>
        <div className="pd-form">
          <label className="pd-field">
            <span className="pd-field-label">Your name</span>
            <input
              className="pd-input"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
          </label>
          <button
            className="pd-btn pd-btn--primary pd-btn--lg"
            disabled={!value.trim() || busy}
            onClick={submit}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Upcoming tab
// ---------------------------------------------------------------------------

function UpcomingTab({ storeSlug }: { storeSlug: string }) {
  const [data, setData] = useState<BookingsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    setError(null);
    customerFetch<BookingsPage>(storeSlug, "/api/me/bookings/?status=upcoming")
      .then(setData)
      .catch(() => setError("Couldn't load bookings."));
  }, [storeSlug]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (error) return <Empty>{error}</Empty>;
  if (!data) return <Empty>Loading…</Empty>;
  if (data.results.length === 0)
    return <Empty>You have no upcoming bookings. See you next time!</Empty>;

  return (
    <section className="pd-step is-active">
      <div className="pd-step-body">
        <ul className="pd-list">
          {data.results.map((b) => (
            <BookingRow key={b.id} booking={b} storeSlug={storeSlug} onChange={reload} />
          ))}
        </ul>
      </div>
    </section>
  );
}

function BookingRow({
  booking,
  storeSlug,
  onChange,
}: {
  booking: MyBooking;
  storeSlug: string;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [reschedOpen, setReschedOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);

  async function cancel() {
    setBusy(true);
    try {
      await customerFetch(storeSlug, `/api/me/bookings/${booking.id}/cancel/`, {
        method: "POST",
      });
      setCancelOpen(false);
      onChange();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const body = (e.body || {}) as { lead_hours?: number };
        alert(
          `Free cancellation closed ${body.lead_hours ?? 24}h before start. Please contact staff.`,
        );
      } else {
        alert("Something went wrong cancelling. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="pd-row">
      <div className="pd-row-main">
        <div className="pd-row-title">{booking.resource.name}</div>
        <div className="pd-row-sub">
          {formatDateTime(booking.start_at)} – {formatDateTime(booking.end_at)}
        </div>
      </div>
      <div className="pd-row-actions">
        <button className="pd-btn pd-btn--ghost" disabled={busy} onClick={() => setReschedOpen(true)}>
          Reschedule
        </button>
        <button className="pd-btn pd-btn--ghost" disabled={busy} onClick={() => setCancelOpen(true)}>
          Cancel
        </button>
      </div>
      {reschedOpen && (
        <RescheduleModal
          storeSlug={storeSlug}
          booking={booking}
          onClose={() => setReschedOpen(false)}
          onDone={() => {
            setReschedOpen(false);
            onChange();
          }}
        />
      )}
      {cancelOpen && (
        <ConfirmModal
          title="Cancel this booking?"
          body="Free cancellation up to 24 hours before start. After that, please contact staff."
          confirmLabel={busy ? "Cancelling…" : "Yes, cancel"}
          onCancel={() => setCancelOpen(false)}
          onConfirm={cancel}
        />
      )}
    </li>
  );
}

function ConfirmModal({
  title,
  body,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="pd-modal" role="dialog" aria-modal="true">
      <div className="pd-modal-card">
        <h3 className="pd-step-title">{title}</h3>
        <p className="pd-fine">{body}</p>
        <div className="pd-row-actions">
          <button className="pd-btn pd-btn--ghost" onClick={onCancel}>
            No, keep it
          </button>
          <button className="pd-btn pd-btn--primary" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function RescheduleModal({
  storeSlug,
  booking,
  onClose,
  onDone,
}: {
  storeSlug: string;
  booking: MyBooking;
  onClose: () => void;
  onDone: () => void;
}) {
  const originalStart = useMemo(() => new Date(booking.start_at), [booking.start_at]);
  const originalEnd = useMemo(() => new Date(booking.end_at), [booking.end_at]);
  const durationMs = originalEnd.getTime() - originalStart.getTime();
  // Pre-fill the picker with original start + 1 day so the customer just
  // picks the new time.
  const defaultStart = new Date(originalStart.getTime() + 24 * 60 * 60 * 1000);
  const [startLocal, setStartLocal] = useState(() => toLocalInput(defaultStart));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    setBusy(true);
    try {
      const start = new Date(startLocal);
      const end = new Date(start.getTime() + durationMs);
      await customerFetch(storeSlug, `/api/me/bookings/${booking.id}/reschedule/`, {
        method: "POST",
        body: JSON.stringify({
          start_at: start.toISOString(),
          end_at: end.toISOString(),
        }),
      });
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("That slot is already taken. Try another time.");
      } else if (e instanceof ApiError && e.status === 400) {
        setError("That time is invalid. Pick a future slot of the same length.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pd-modal" role="dialog" aria-modal="true">
      <div className="pd-modal-card">
        <h3 className="pd-step-title">Reschedule {booking.resource.name}</h3>
        <p className="pd-fine">
          Pick a new start time. Same duration as the original booking.
        </p>
        <label className="pd-field">
          <span className="pd-field-label">New start</span>
          <input
            className="pd-input"
            type="datetime-local"
            value={startLocal}
            onChange={(e) => setStartLocal(e.target.value)}
          />
        </label>
        {error && (
          <div className="pd-error">
            <span className="pd-error-dot" />
            {error}
          </div>
        )}
        <div className="pd-row-actions">
          <button className="pd-btn pd-btn--ghost" disabled={busy} onClick={onClose}>
            Back
          </button>
          <button className="pd-btn pd-btn--primary" disabled={busy} onClick={submit}>
            {busy ? "Saving…" : "Confirm reschedule"}
          </button>
        </div>
      </div>
    </div>
  );
}

function toLocalInput(d: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ---------------------------------------------------------------------------
// History tab
// ---------------------------------------------------------------------------

function HistoryTab({ storeSlug }: { storeSlug: string }) {
  const [data, setData] = useState<BookingsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setError(null);
    customerFetch<BookingsPage>(
      storeSlug,
      `/api/me/bookings/?status=past&offset=${offset}&limit=20`,
    )
      .then((page) => {
        setData((prev) =>
          prev && offset > 0
            ? { ...page, results: [...prev.results, ...page.results] }
            : page,
        );
      })
      .catch(() => setError("Couldn't load history."));
  }, [storeSlug, offset]);

  if (error) return <Empty>{error}</Empty>;
  if (!data) return <Empty>Loading…</Empty>;
  if (data.results.length === 0) return <Empty>No past bookings yet.</Empty>;

  return (
    <section className="pd-step is-active">
      <div className="pd-step-body">
        <ul className="pd-list">
          {data.results.map((b) => (
            <li key={b.id} className="pd-row">
              <div className="pd-row-main">
                <div className="pd-row-title">{b.resource.name}</div>
                <div className="pd-row-sub">{formatDateTime(b.start_at)}</div>
              </div>
              <div className="pd-row-actions">
                <span className={`pd-chip pd-chip--ghost pd-status-${b.status}`}>{b.status}</span>
              </div>
            </li>
          ))}
        </ul>
        {data.has_more && (
          <button
            className="pd-btn pd-btn--ghost"
            onClick={() => setOffset((o) => o + 20)}
          >
            Load more
          </button>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Loyalty tab
// ---------------------------------------------------------------------------

function LoyaltyTab({ storeSlug }: { storeSlug: string }) {
  const [data, setData] = useState<MembershipPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    setError(null);
    customerFetch<MembershipPayload>(storeSlug, "/api/me/membership/")
      .then(setData)
      .catch(() => setError("Couldn't load loyalty."));
  }, [storeSlug]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function redeem(rewardId: number) {
    try {
      await customerFetch(storeSlug, "/api/me/redeem/", {
        method: "POST",
        body: JSON.stringify({ reward_id: rewardId }),
      });
      reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        alert("Not enough points yet — keep playing!");
      } else {
        alert("Couldn't redeem. Please try again.");
      }
    }
  }

  if (error) return <Empty>{error}</Empty>;
  if (!data) return <Empty>Loading…</Empty>;

  return (
    <section className="pd-step is-active">
      <div className="pd-step-body">
        <div className="pd-summary">
          <div className="pd-summary-row pd-summary-row--total">
            <span className="pd-summary-key">Balance</span>
            <span className="pd-summary-val pd-mono">{data.balance} pts</span>
          </div>
          {data.tier && (
            <div className="pd-summary-row">
              <span className="pd-summary-key">Tier</span>
              <span className="pd-summary-val">{data.tier.name}</span>
            </div>
          )}
          {data.next_tier && data.points_to_next_tier !== null && (
            <div className="pd-summary-row">
              <span className="pd-summary-key">Next: {data.next_tier.name}</span>
              <span className="pd-summary-val pd-mono">
                {data.points_to_next_tier} pts to go
              </span>
            </div>
          )}
        </div>
        <h2 className="pd-step-title" style={{ marginTop: 20 }}>
          Rewards you can redeem
        </h2>
        {data.available_rewards.length === 0 ? (
          <Empty>No rewards available at your current balance.</Empty>
        ) : (
          <ul className="pd-list">
            {data.available_rewards.map((r) => (
              <li key={r.id} className="pd-row">
                <div className="pd-row-main">
                  <div className="pd-row-title">{r.name}</div>
                  <div className="pd-row-sub pd-mono">{r.cost_points} pts</div>
                </div>
                <div className="pd-row-actions">
                  <button className="pd-btn pd-btn--primary" onClick={() => redeem(r.id)}>
                    Redeem
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Profile tab
// ---------------------------------------------------------------------------

function ProfileTab({
  storeSlug,
  customer,
  onCustomerChange,
}: {
  storeSlug: string;
  customer: SessionCustomer;
  onCustomerChange: (c: SessionCustomer) => void;
}) {
  const router = useRouter();
  const [name, setName] = useState(customer.name);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState(0);

  async function saveName() {
    setBusy(true);
    try {
      const next = await customerFetch<SessionCustomer>(storeSlug, "/api/me/", {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      onCustomerChange(next);
      setSavedAt(Date.now());
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await customerFetch(storeSlug, "/api/customer-auth/logout/", { method: "POST" });
    } finally {
      router.push(`/s/${storeSlug}/book`);
    }
  }

  return (
    <section className="pd-step is-active">
      <div className="pd-step-body">
        <div className="pd-form">
          <label className="pd-field">
            <span className="pd-field-label">Display name</span>
            <input
              className="pd-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            />
          </label>
          <button
            className="pd-btn pd-btn--primary"
            disabled={busy || name === customer.name || !name.trim()}
            onClick={saveName}
          >
            {busy ? "Saving…" : "Save"}
          </button>
          {savedAt > 0 && <p className="pd-fine">Saved.</p>}
          <label className="pd-field">
            <span className="pd-field-label">Phone (read-only)</span>
            <input className="pd-input pd-mono" value={customer.phone} disabled readOnly />
          </label>
          <p className="pd-fine">
            To change your phone number, please ask staff at the front desk.
          </p>
          <button className="pd-btn pd-btn--ghost" onClick={logout}>
            Log out
          </button>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <section className="pd-step is-active">
      <div className="pd-step-body">
        <div className="pd-empty">{children}</div>
      </div>
    </section>
  );
}
