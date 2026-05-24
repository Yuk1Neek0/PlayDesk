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
import { StoreSwitcher } from "@/components/admin/store-switcher";

export default function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <StoreProvider>
      <AdminSubHeader />
      {children}
    </StoreProvider>
  );
}

function AdminSubHeader() {
  return (
    <div
      className="pd-admin-subheader"
      style={{
        display: "flex",
        justifyContent: "flex-end",
        padding: "8px 24px 0",
      }}
    >
      <StoreSwitcher />
    </div>
  );
}
