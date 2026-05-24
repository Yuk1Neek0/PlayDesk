"use client";

// /staff/login/ form — client component.
//
// Submits {username, password} to POST /api/staff/login/. The backend
// sets the Django session cookie on success; we then push to `next`
// (defaults to /admin) and let <StaffSessionProvider> re-validate via
// /api/staff/me/ when the admin layout mounts.

import { useState } from "react";

interface LoginFormProps {
  /** URL to land on after a successful login. */
  next: string;
}

type Status = "idle" | "submitting" | "error";

export default function LoginForm({ next }: LoginFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("submitting");
    setErrorMsg("");
    try {
      const resp = await fetch("/api/staff/login/", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (resp.status === 200) {
        // Hard navigation so the server-rendered admin layout picks up
        // the freshly-minted sessionid cookie cleanly.
        window.location.assign(next);
        return;
      }
      let detail: string;
      if (resp.status === 401) detail = "Invalid credentials.";
      else if (resp.status === 403) detail = "This account isn't a staff account.";
      else if (resp.status === 429)
        detail = "Too many attempts. Try again in a few minutes.";
      else detail = `Sign-in failed (${resp.status}).`;
      setErrorMsg(detail);
      setStatus("error");
    } catch {
      setErrorMsg("Network error. Please try again.");
      setStatus("error");
    }
  }

  return (
    <div className="max-w-md mx-auto px-4 py-16">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Staff sign-in</h1>
      <p className="text-gray-500 mb-8">
        Sign in with your PlayDesk staff account.
      </p>

      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-lg shadow p-6 space-y-4"
      >
        <div>
          <label
            htmlFor="username"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Username
          </label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          />
        </div>

        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2"
          />
        </div>

        {status === "error" && errorMsg && (
          <div
            role="alert"
            className="text-sm text-red-600 border border-red-200 bg-red-50 rounded px-3 py-2"
          >
            {errorMsg}
          </div>
        )}

        <button
          type="submit"
          disabled={status === "submitting"}
          className="w-full bg-gray-800 hover:bg-gray-700 disabled:bg-gray-400 text-white py-3 rounded-lg font-medium transition"
        >
          {status === "submitting" ? "Signing in…" : "Sign in"}
        </button>

        <p className="text-xs text-gray-400 text-center pt-2">
          Forgot your password? Contact your administrator.
        </p>
      </form>
    </div>
  );
}
