// Rotating in-store check-in landing page (v11a).
//
// Customer scans the door QR → lands here with `?k=<rotating-key>`.
// We SSR-resolve the key against the backend. A 410 (expired/unknown)
// renders an "ask staff" card without any client JS. A 200 hands off
// to `<RotatingCheckinClient>` for the phone → OTP → booking flow.

import { fetchStoreBrand } from "@/lib/store-brand";

import RotatingCheckinClient from "./RotatingCheckinClient";

export const dynamic = "force-dynamic";

interface LookupResult {
  store_slug: string;
  store_name: string;
  expires_at: string;
}

function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

async function lookupKey(key: string): Promise<LookupResult | null> {
  const origin = backendOrigin();
  try {
    const resp = await fetch(`${origin}/api/c-in/lookup-key/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as LookupResult;
  } catch {
    return null;
  }
}

function ExpiredCard({ reason }: { reason: string }) {
  return (
    <main className="pd-checkin-page">
      <section className="pd-checkin-card" data-testid="rotating-checkin-expired">
        <div className="pd-checkin-body">
          <div className="pd-checkin-greeting">Hi there,</div>
          <div className="pd-checkin-status pd-checkin-status--expired">{reason}</div>
        </div>
      </section>
    </main>
  );
}

export default async function RotatingCheckinPage(props: {
  searchParams: Promise<{ k?: string }>;
}) {
  const params = await props.searchParams;
  const key = (params.k ?? "").trim();
  if (!key) {
    return (
      <ExpiredCard reason="No check-in code in the URL — please scan the QR at the door." />
    );
  }
  const lookup = await lookupKey(key);
  if (lookup === null) {
    return (
      <ExpiredCard reason="Code expired — please ask staff for the current QR." />
    );
  }
  const brand = await fetchStoreBrand(lookup.store_slug);
  return (
    <RotatingCheckinClient
      brand={brand}
      storeSlug={lookup.store_slug}
      storeName={lookup.store_name}
      keyValue={key}
    />
  );
}
