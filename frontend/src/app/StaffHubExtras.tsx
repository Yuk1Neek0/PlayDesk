"use client";

// Renders a hub-card link to /admin/settings/checkin/display, but only
// when the visitor has a valid staff session. Lives next to the four
// server-rendered hub entries in `/app/page.tsx`. Customer visitors never
// see it; staff get a one-tap shortcut to the door QR display.
//
// Implementation note: this is a client component because the staff
// session is cookie-based + checked via /api/staff/me/. Doing the SSR
// check in the hub page would require the page itself to be `dynamic` +
// session-aware, which complicates QR-card / bookmark callers. The
// trade-off is one extra paint: the 5th entry appears after hydration if
// staff, otherwise stays absent.

import Link from "next/link";

import { useStaffSession } from "@/lib/staff-session";

export default function StaffHubExtras() {
  const { user, ready } = useStaffSession();
  if (!ready || !user?.is_staff) return null;
  return (
    <Link
      className="pd-hub-card"
      href="/admin/settings/checkin/display"
      data-testid="hub-door-qr"
    >
      <div className="pd-hub-card-eyebrow">Staff only</div>
      <div className="pd-hub-card-title">Door QR</div>
      <p className="pd-hub-card-body">
        Open the rotating check-in code fullscreen — display on the lobby tablet.
      </p>
      <span className="pd-hub-card-arrow" aria-hidden>
        →
      </span>
    </Link>
  );
}
