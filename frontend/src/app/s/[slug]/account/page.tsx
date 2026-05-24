// Server entry for the customer-portal at /s/[slug]/account.
//
// SSR check: the `pd_customer_session` cookie is signed (server-only),
// so we can't decode it client-side. Instead we forward it to the backend
// `/api/me/` endpoint with the URL slug header; a 200 means a valid
// session (render the dashboard shell), anything else means we render
// the login form. This SSR roundtrip keeps the initial paint deterministic
// — no flash-of-login state on a logged-in customer's reload.
//
// `dynamic = "force-dynamic"` so the cookie check runs on every request.

import { cookies } from "next/headers";

import AccountDashboard from "./AccountDashboard";
import LoginForm from "./LoginForm";
import { fetchStoreBrand } from "@/lib/store-brand";

export const dynamic = "force-dynamic";

interface Params {
  slug: string;
}

interface SessionCustomer {
  id: number;
  name: string;
  phone: string;
  store_slug: string;
}

function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

async function loadSession(slug: string, cookieHeader: string): Promise<SessionCustomer | null> {
  // SSR fetch to /api/me/ with the original Cookie header forwarded so
  // the backend `CustomerSessionMiddleware` can validate the signed
  // session. The X-PD-Store-Slug header makes `request.store` match the
  // URL slug — a cookie bound to a different store will fall through to
  // `request.customer = None` and yield 401.
  try {
    const resp = await fetch(`${backendOrigin()}/api/me/`, {
      headers: {
        cookie: cookieHeader,
        "X-PD-Store-Slug": slug,
      },
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as SessionCustomer;
  } catch {
    return null;
  }
}

export default async function Page(props: { params: Promise<Params> }) {
  const params = await props.params;
  const cookieStore = await cookies();
  // Serialise every cookie back into a single header string for SSR fetch.
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  const [brand, session] = await Promise.all([
    fetchStoreBrand(params.slug),
    cookieHeader ? loadSession(params.slug, cookieHeader) : Promise.resolve(null),
  ]);

  if (session) {
    return <AccountDashboard brand={brand} storeSlug={params.slug} initialCustomer={session} />;
  }
  return <LoginForm brand={brand} storeSlug={params.slug} />;
}
