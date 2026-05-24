// /staff/login/ — server component.
//
// SSR optimisation: if the request already carries a valid sessionid
// cookie, we round-trip /api/staff/me/ from the server and 302 to
// /admin instead of rendering the login form (saves a render + a
// client-side redirect flicker). If the cookie's missing or invalid,
// we render the login form and let the client take over.
//
// Falls back gracefully — any backend hiccup just shows the form.

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import LoginForm from "./LoginForm";

export const dynamic = "force-dynamic";

function backendOrigin(): string {
  // Same convention used by `app/page.tsx` + `lib/store-brand.ts`.
  return process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
}

async function isAuthenticated(): Promise<boolean> {
  const sessionCookie = cookies().get("sessionid");
  if (!sessionCookie) return false;
  try {
    const resp = await fetch(`${backendOrigin()}/api/staff/me/`, {
      cache: "no-store",
      headers: { Cookie: `sessionid=${sessionCookie.value}` },
    });
    return resp.status === 200;
  } catch {
    return false;
  }
}

interface PageProps {
  searchParams?: { next?: string };
}

export default async function StaffLoginPage({ searchParams }: PageProps) {
  if (await isAuthenticated()) {
    const next = searchParams?.next || "/admin";
    redirect(next);
  }
  return <LoginForm next={searchParams?.next || "/admin"} />;
}
