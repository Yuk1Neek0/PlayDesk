// Public One-QR landing page.
//
// Server-rendered: the actions list and store branding ship in the first
// HTML response so a phone scan resolves in one round-trip. A small
// client component (QRLanding) records the scan event and handles chip
// clicks via navigator.sendBeacon + immediate redirect — the redirect is
// never blocked on the analytics call.
//
// Memberships extension: if the `pd_customer` cookie resolves to a real
// customer for this store, we resolve their tier server-side and pass it
// to QRLanding so a tiny tier badge renders in the header. Anonymous
// visitors get no badge — the badge endpoint returns `{tier: null}` for
// any unresolved / mismatched cookie, never a 4xx.

import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { type QRPublicPayload } from "@/lib/api";

import QRLanding from "./QRLanding";

interface Params {
  slug: string;
}

export interface TierBadge {
  id: number;
  name: string;
  perks_text: string;
}

function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

async function loadPayload(slug: string): Promise<QRPublicPayload | null> {
  // SSR runs inside the Next.js container, where same-origin `/api/...`
  // does not resolve (the rewrite proxy in next.config.mjs only applies
  // to browser requests). Build an absolute URL to the backend via the
  // server-only `BACKEND_ORIGIN` env (set by docker-compose).
  const origin = backendOrigin();
  try {
    const resp = await fetch(`${origin}/api/qr/${encodeURIComponent(slug)}/`, {
      // Disable Next.js's data cache so a freshly-toggled action shows up
      // on the next scan.
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as QRPublicPayload;
  } catch {
    return null;
  }
}

async function loadTierBadge(
  customerId: number,
  storeId: number,
): Promise<TierBadge | null> {
  const origin = backendOrigin();
  try {
    const resp = await fetch(
      `${origin}/api/qr/tier/?customer_id=${customerId}&store=${storeId}`,
      { cache: "no-store" },
    );
    if (!resp.ok) return null;
    const body = (await resp.json()) as { tier: TierBadge | null };
    return body.tier ?? null;
  } catch {
    return null;
  }
}

export default async function QRPage(props: { params: Promise<Params> }) {
  const params = await props.params;
  const payload = await loadPayload(params.slug);
  if (!payload) notFound();

  // Identified-visitor tier lookup. The pd_customer cookie carries the
  // integer Customer pk; if it doesn't resolve to a customer for this
  // store, the badge endpoint quietly returns `{tier: null}`.
  let tier: TierBadge | null = null;
  const cookieStore = await cookies();
  const raw = cookieStore.get("pd_customer")?.value;
  if (raw) {
    const cid = Number(raw);
    if (Number.isFinite(cid) && cid > 0) {
      tier = await loadTierBadge(cid, payload.store.id);
    }
  }

  return <QRLanding payload={payload} tier={tier} />;
}
