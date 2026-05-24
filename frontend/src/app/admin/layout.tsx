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

import { StoreProvider } from "@/lib/store-context";
import { StaffSessionProvider, useStaffSession } from "@/lib/staff-session";
import { StoreSwitcher } from "@/components/admin/store-switcher";

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
  return (
    <div
      className="pd-admin-subheader"
      style={{
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
        gap: 12,
        padding: "8px 24px 0",
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
