// Server entry for the customer-facing store-scoped booking page.
//
// Mirrors today's `app/page.tsx` but receives `params.slug` from the URL
// segment `/s/[slug]/book` and threads it through to:
//
//   - `fetchStoreBrand(slug)` — so the SSR'd header carries the URL
//     store's logo + accent, never the default store's.
//   - `<BookingPage storeSlug=… />` — the client component then injects
//     `X-PD-Store-Slug: <slug>` on every API call via `customerFetch`
//     so the booking is created against the URL store regardless of
//     cookie / fallback state.
//
// `dynamic = "force-dynamic"` opts out of static prerender: the brand
// fetch is `cache: "no-store"` so an admin brand edit shows on the
// next request without a rebuild.

import BookingPage from "./BookingPage";
import { fetchStoreBrand } from "@/lib/store-brand";

export const dynamic = "force-dynamic";

interface Params {
  slug: string;
}

export default async function Page(props: { params: Promise<Params> }) {
  const params = await props.params;
  const brand = await fetchStoreBrand(params.slug);
  return <BookingPage brand={brand} storeSlug={params.slug} />;
}
