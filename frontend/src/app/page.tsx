// Root `/` is now a server-side 302 redirect to the default store's
// booking page (`/s/<slug>/book`). Why:
//
//   1. v6 multi-location moves the booking flow under `/s/[slug]/book`
//      so the URL carries the store context. Existing bookmarks /
//      QR-card prints that still point at `/` must keep working — hence
//      the redirect rather than a 404.
//   2. The redirect target is fetched from `/api/public/default-store/`
//      (not hardcoded) so a deployment that drops or renames its
//      flagship store still resolves correctly without a frontend
//      redeploy.
//   3. Server-side `redirect()` from `next/navigation` (302, default)
//      runs before any HTML ships, so direct navigation and crawlers
//      both see the canonical store URL.
//
// `dynamic = "force-dynamic"` keeps the lookup live — a brand new store
// added in Django admin shows up as the default on the next request.

import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

const FALLBACK_SLUG = "playdesk-flagship";

function backendOrigin(): string {
  // Server-only var (set by docker-compose). Matches the SSR-fetch pattern
  // in `lib/store-brand.ts` and `app/qr/[slug]/page.tsx`.
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
    // Backend unreachable — fall back to the well-known flagship slug
    // rather than rendering a blank page. The fallback matches
    // seed_data.py's flagship slug.
    return FALLBACK_SLUG;
  }
}

export default async function Page() {
  const slug = await loadDefaultSlug();
  redirect(`/s/${slug}/book`);
}
