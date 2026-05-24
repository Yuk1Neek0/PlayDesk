// Public per-booking check-in page (v10b checkin).
//
// SSR-fetches `GET /api/c/<token>/` from the backend, then hands off
// to `<CheckInClient>` for the interactive POST. The token IS the
// credential — no auth required. A token that doesn't resolve to a
// booking renders the standard 404 page.
//
// Mirrors the `/qr/[slug]` SSR pattern: the same `BACKEND_ORIGIN`
// env trick is used because the Next.js rewrite proxy only applies
// to browser requests, not server-side ones.

import { notFound } from "next/navigation";

import { fetchStoreBrand } from "@/lib/store-brand";

import CheckInClient, { type CheckInPayload } from "./CheckInClient";

export const dynamic = "force-dynamic";

interface Params {
  token: string;
}

function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

async function loadPayload(token: string): Promise<CheckInPayload | null> {
  const origin = backendOrigin();
  try {
    const resp = await fetch(`${origin}/api/c/${encodeURIComponent(token)}/`, {
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as CheckInPayload;
  } catch {
    return null;
  }
}

export default async function CheckInPage(props: { params: Promise<Params> }) {
  const params = await props.params;
  const payload = await loadPayload(params.token);
  if (payload === null) notFound();
  // Brand is best-effort; an error here returns the default branding.
  const brand = await fetchStoreBrand(payload.store_slug);
  return <CheckInClient initial={payload} brand={brand} token={params.token} />;
}
