"use client";

// Persistent top navigation, ported from the Claude Design handoff
// (playdeck/project/src/app.jsx). Hash routing in the prototype is replaced
// with Next.js routes + usePathname for the active state.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/pd-ui";

const LINKS: { href: string; label: string }[] = [
  { href: "/", label: "Book" },
  { href: "/chat", label: "AI Front Desk" },
  { href: "/admin", label: "Admin" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="pd-nav">
      <Link className="pd-nav-brand" href="/">
        <span className="pd-brand-mark" aria-hidden>
          <Icon.logo size={20} />
        </span>
        <span className="pd-brand-name">PlayDesk</span>
        <span className="pd-brand-loc">工大店 · Shenzhen</span>
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
