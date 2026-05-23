// Public One-QR landing page.
//
// Server-rendered: the actions list and store branding ship in the first
// HTML response so a phone scan resolves in one round-trip. A small
// client component (QRLanding) records the scan event and handles chip
// clicks via navigator.sendBeacon + immediate redirect — the redirect is
// never blocked on the analytics call.

import { notFound } from "next/navigation";

import { getQRPublic, type QRPublicPayload } from "@/lib/api";

import QRLanding from "./QRLanding";

interface Params {
  slug: string;
}

async function loadPayload(slug: string): Promise<QRPublicPayload | null> {
  // SSR runs server-side where `fetch` resolves directly to the Django
  // backend via the rewrite proxy. Catch a 404 and surface it to the
  // Next.js notFound flow rather than crashing the render.
  try {
    return await getQRPublic(slug);
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
