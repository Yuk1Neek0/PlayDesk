/** @type {import('next').NextConfig} */

// The Django backend ships no CORS headers, so the browser cannot call it
// cross-origin. Proxy `/api/*` through the Next.js server (same-origin to the
// browser); Next forwards server-side to the backend, where CORS is moot.
// `BACKEND_ORIGIN` is a server-only var: `backend:8000` inside Compose,
// `127.0.0.1:8000` for local dev.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  // Emit a standalone server bundle so the Docker image can run `node server.js`.
  output: "standalone",

  // Django's URLConf requires trailing slashes. By default Next.js 308-redirects
  // `/api/resources/` → `/api/resources` (stripping the slash) *before* the
  // rewrite runs, which then hits Django slash-less and 301s / 500s on POST.
  // Skipping that redirect, plus appending the slash in the rewrite destination
  // (Next's `:path*` capture drops it), keeps the proxied path slash-terminated.
  skipTrailingSlashRedirect: true,

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*/`,
      },
    ];
  },
};

export default nextConfig;
