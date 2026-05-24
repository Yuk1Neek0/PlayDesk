// Server entry for the booking page. SSR-fetches the store branding (logo +
// accent) so the first HTML response already carries the right colours and
// logo — no flash of default branding. The interactive booking flow lives in
// the client component BookingPage.tsx and receives `brand` as a prop.
//
// `dynamic = "force-dynamic"` opts out of Next's build-time static prerender:
// the helper uses `cache: "default"` so concurrent SSR renders dedupe inside
// the endpoint's 60s `max-age=60` window, but a brand change must surface on
// the next request — not require a rebuild.

import BookingPage from "./BookingPage";
import { fetchStoreBrand } from "@/lib/store-brand";

export const dynamic = "force-dynamic";

export default async function Page() {
  const brand = await fetchStoreBrand();
  return <BookingPage brand={brand} />;
}
