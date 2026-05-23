// Public One-QR landing page.
//
// Server-rendered: the actions list and store branding ship in the first
// HTML response so a phone scan resolves in one round-trip. A small
// client component (QRLanding) records the scan event and handles chip
// clicks via navigator.sendBeacon + immediate redirect — the redirect is
// never blocked on the analytics call.

import { notFound } from "next/navigation";

import { type QRPublicPayload } from "@/lib/api";

import QRLanding from "./QRLanding";

interface Params {
  slug: string;
}

async function loadPayload(slug: string): Promise<QRPublicPayload | null> {
  // SSR runs inside the Next.js container, where same-origin `/api/...`
  // does not resolve (the rewrite proxy in next.config.mjs only applies
  // to browser requests). Build an absolute URL to the backend via the
  // server-only `BACKEND_ORIGIN` env (set by docker-compose).
  const origin = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
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

export default async function QRPage(props: { params: Promise<Params> }) {
  const params = await props.params;
  const payload = await loadPayload(params.slug);
  if (!payload) notFound();
  return <QRLanding payload={payload} />;
}
