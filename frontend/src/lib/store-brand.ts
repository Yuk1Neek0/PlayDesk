// SSR-side fetch helper for the public store-brand endpoint. Consumed by
// both the booking page (`app/page.tsx`) and the QR landing page
// (`app/qr/[slug]/page.tsx`) so the branding read goes through a single
// callsite shape.
//
// On any error (network or non-2xx), this returns the default-degraded
// shape — a transient backend hiccup must NOT break the booking page
// render. The page just renders with the default PlayDesk branding.

export interface StoreBrand {
  name: string;
  logo_url: string | null;
  accent: string | null;
}

const DEFAULT_BRAND: StoreBrand = {
  name: "PlayDesk",
  logo_url: null,
  accent: null,
};

function backendOrigin(): string {
  // Server-only var (set by docker-compose). Matches the SSR-fetch pattern
  // established in app/qr/[slug]/page.tsx.
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

export async function fetchStoreBrand(): Promise<StoreBrand> {
  const origin = backendOrigin();
  try {
    const resp = await fetch(`${origin}/api/public/store-brand/`, {
      // `cache: "no-store"` so an admin updating Store.brand sees the change
      // on the very next request. Next.js's Data Cache would otherwise hold
      // the response for the duration of the dev session, which broke the
      // branded-booking.e2e.ts test (it mutates brand and expects the next
      // navigation to reflect it). The endpoint itself is one indexed read
      // (~5ms) so dropping the data-cache layer is essentially free.
      cache: "no-store",
    });
    if (!resp.ok) return DEFAULT_BRAND;
    const body = (await resp.json()) as Partial<StoreBrand>;
    return {
      name: typeof body.name === "string" ? body.name : DEFAULT_BRAND.name,
      logo_url: typeof body.logo_url === "string" ? body.logo_url : null,
      accent: typeof body.accent === "string" ? body.accent : null,
    };
  } catch {
    return DEFAULT_BRAND;
  }
}
