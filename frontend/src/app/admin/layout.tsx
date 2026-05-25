"use client";

// Admin layout — wraps every /admin/* route in <StoreProvider> so the
// staff app knows which store the admin is currently viewing. The
// <StoreSwitcher /> chip group lives in a thin sub-header below the
// global Nav; in single-store deployments the switcher hides itself.
//
// The store-aware bits at the top of the global Nav (the "Downtown ·
// Toronto" pill) read the same StoreContext via `useCurrentStore()` and
// automatically reflect the current store while a staff user is on
// /admin/*.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { StoreProvider } from "@/lib/store-context";
import { StaffSessionProvider, useStaffSession } from "@/lib/staff-session";
import { StoreSwitcher } from "@/components/admin/store-switcher";

// Settings entries shown as chip links in the admin sub-header. Adding
// more = append here; the active-state styling is automatic via pathname.
const SETTINGS_LINKS: { href: string; label: string }[] = [
  { href: "/admin/settings/checkin", label: "Door QR" },
  { href: "/admin/settings/payments", label: "Payments" },
];

export default function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // v10a — StaffSessionProvider wraps everything so an expired / missing
  // session redirects to /staff/login before any admin page renders.
  // StoreProvider sits inside it; the store fetch only matters after
  // we know the visitor is authenticated.
  return (
    <StaffSessionProvider>
      <StoreProvider>
        <AdminGate>
          <AdminSubHeader />
          {children}
        </AdminGate>
      </StoreProvider>
    </StaffSessionProvider>
  );
}

/**
 * Holds rendering of the admin tree until the session check completes,
 * then renders nothing while an anonymous visitor is being redirected
 * to /staff/login (the provider's effect handles the redirect).
 */
function AdminGate({ children }: { children: React.ReactNode }) {
  const { user, ready } = useStaffSession();
  if (!ready) {
    return (
      <div className="pd-admin" aria-busy="true">
        <div className="pd-empty">Loading…</div>
      </div>
    );
  }
  if (!user) return null;
  return <>{children}</>;
}

function AdminSubHeader() {
  const { user, logout } = useStaffSession();
  const pathname = usePathname();
  return (
    <div
      className="pd-admin-subheader"
      style={{
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
        gap: 12,
        padding: "8px 24px 0",
        flexWrap: "wrap",
      }}
    >
      {user && (
        <span
          data-testid="staff-username"
          className="pd-chip"
          style={{ fontSize: 12 }}
        >
          Signed in as <strong>{user.username}</strong>
        </span>
      )}
      {SETTINGS_LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname?.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            className={`pd-chip pd-chip--ghost ${active ? "is-active" : ""}`}
            style={{ fontSize: 12 }}
          >
            {label}
          </Link>
        );
      })}
      <StoreSwitcher />
      {user && (
        <button
          type="button"
          onClick={() => void logout()}
          className="pd-btn pd-btn--ghost pd-btn--sm"
          data-testid="staff-logout"
        >
          Logout
        </button>
      )}
    </div>
  );
}
