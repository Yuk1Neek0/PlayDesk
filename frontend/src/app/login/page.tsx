// /login — historically the placeholder "one-click demo sign-in" page.
// v10a retires it: customers are sent to the real per-store customer
// portal (`/s/<default>/account`). Staff who somehow land here will
// be bounced again by the customer portal's auth + the admin gate at
// /staff/login.
//
// This stays as a 302 redirect rather than a 404 so any old bookmarks
// or e-mail links keep landing somewhere useful. The default-slug
// lookup mirrors `app/page.tsx` so a renamed flagship store still
// resolves without a frontend redeploy.

import { redirect } from "next/navigation";

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

export default async function LoginPage() {
  const slug = await loadDefaultSlug();
  redirect(`/s/${slug}/account`);
}
