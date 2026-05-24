// Root `/` is the PlayDesk customer-facing hub. Phase 2 retires the
// v6-era 302 redirect to `/s/<default>/book` in favour of a real landing
// with four explicit entries. See DESIGN_AUDIT.md §4 for the rationale.
//
// Four entries:
//   1. Book now             → /s/<default>/book   (most prominent)
//   2. My account           → /s/<default>/account
//   3. Talk to front desk   → /chat
//   4. Staff sign in        → /staff/login
//
// The default store's slug + brand are still fetched server-side from
// `/api/public/default-store/` and `/api/public/store-brand/` so printed
// QR cards or bookmarks pointing at `/` keep working — they just land on
// a hub now instead of being redirected. The mobile layout stacks the
// four entries vertically with Book as the visual lead; desktop falls
// into a 2×2 grid.

import Link from "next/link";

import { Icon } from "@/components/pd-ui";
import { fetchStoreBrand, type StoreBrand } from "@/lib/store-brand";

export const dynamic = "force-dynamic";

const FALLBACK_SLUG = "playdesk-flagship";

function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

async function loadDefaultSlug(): Promise<string> {
  const origin = backendOrigin();
  try {
    const resp = await fetch(`${origin}/api/public/default-store/`, {
      cache: "no-store",
    });
    if (!resp.ok) return FALLBACK_SLUG;
    const body = (await resp.json()) as { slug: string | null };
    return typeof body.slug === "string" && body.slug ? body.slug : FALLBACK_SLUG;
  } catch {
    return FALLBACK_SLUG;
  }
}

interface HubEntry {
  href: string;
  eyebrow: string;
  title: string;
  body: string;
  primary?: boolean;
}

export default async function HubPage() {
  const slug = await loadDefaultSlug();
  const brand: StoreBrand = await fetchStoreBrand(slug);

  const entries: HubEntry[] = [
    {
      href: `/s/${encodeURIComponent(slug)}/book`,
      eyebrow: "Book a session",
      title: "Book now",
      body: "Pick a station, a date, and a time. Pay at the door or by Stripe.",
      primary: true,
    },
    {
      href: `/s/${encodeURIComponent(slug)}/account`,
      eyebrow: "Loyalty + history",
      title: "My account",
      body: "Sign in with your phone to manage bookings and rewards.",
    },
    {
      href: "/chat",
      eyebrow: "AI front desk",
      title: "Talk to front desk",
      body: "Ask about availability, pricing, or game titles in plain language.",
    },
    {
      href: "/staff/login",
      eyebrow: "Staff only",
      title: "Staff sign in",
      body: "Open the admin dashboard. Requires a PlayDesk staff account.",
    },
  ];

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
        <div className="pd-eyebrow">{brand.name}</div>
        <h1 className="pd-page-title">
          Welcome to
          <br />
          the front desk.
        </h1>
        <p className="pd-page-sub">
          Game lounge bookings, loyalty, and a 24/7 AI host — pick where to land.
        </p>
      </header>

      <section className="pd-hub" aria-label="Where to next">
        {entries.map((e) => (
          <Link
            key={e.href}
            className={`pd-hub-card ${e.primary ? "pd-hub-card--primary" : ""}`}
            href={e.href}
          >
            <div className="pd-hub-card-eyebrow">{e.eyebrow}</div>
            <div className="pd-hub-card-title">{e.title}</div>
            <p className="pd-hub-card-body">{e.body}</p>
            <span className="pd-hub-card-arrow" aria-hidden>
              →
            </span>
          </Link>
        ))}
      </section>
    </div>
  );
}
