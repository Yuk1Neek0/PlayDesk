"use client";

// Persistent top navigation, ported from the Claude Design handoff
// (playdeck/project/src/app.jsx). Hash routing in the prototype is replaced
// with Next.js routes + usePathname for the active state.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/pd-ui";
import { useCurrentStore } from "@/lib/store-context";

// Default brand sub-label for customer pages (no StoreProvider mounted).
// On /admin/*, the admin layout wraps children in <StoreProvider>, so this
// hook returns the actual current store and we render its name instead.
const DEFAULT_BRAND_LOC = "Downtown · Toronto";

// Customer-facing navigation. /admin is intentionally absent — the staff
// dashboard is reached via Sign in and gated by the staff role.
const LINKS: { href: string; label: string }[] = [
  { href: "/", label: "Book" },
  { href: "/chat", label: "AI Front Desk" },
  { href: "/checkin", label: "Check in" },
];

export default function Nav() {
  const pathname = usePathname();
  const { current } = useCurrentStore();

  // Customer-facing QR landing pages are scanned from the front desk —
  // they intentionally render without any app chrome.
  if (pathname?.startsWith("/qr/")) return null;

  return (
    <nav className="pd-nav">
      <Link className="pd-nav-brand" href="/">
        <span className="pd-brand-mark" aria-hidden>
          <Icon.logo size={20} />
        </span>
        <span className="pd-brand-name">PlayDesk</span>
        <span className="pd-brand-loc">{current?.name ?? DEFAULT_BRAND_LOC}</span>
      </Link>
      <div className="pd-nav-links">
        {LINKS.map(({ href, label }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`pd-nav-link ${active ? "is-active" : ""}`}
            >
              {label}
              {active && <span className="pd-nav-link-underline" />}
            </Link>
          );
        })}
      </div>
      <div className="pd-nav-r">
        <button className="pd-icon-btn" aria-label="Search">
          <Icon.search size={16} />
        </button>
        <Link className="pd-btn pd-btn--ghost pd-btn--sm" href="/admin">
          Sign in
        </Link>
      </div>
    </nav>
  );
}
