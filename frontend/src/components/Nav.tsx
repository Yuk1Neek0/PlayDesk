"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export default function Nav() {
  const { user, logout } = useAuth();

  return (
    <nav className="bg-gray-900 text-white px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-lg tracking-tight">PlayDesk</span>
      <Link href="/" className="hover:text-gray-300">
        Book
      </Link>
      <Link href="/chat" className="hover:text-gray-300">
        AI Front Desk
      </Link>
      <Link href="/admin" className="hover:text-gray-300">
        Admin
      </Link>
      <div className="ml-auto flex items-center gap-4">
        {user ? (
          <>
            <span className="text-sm text-gray-400">
              {user.name} ({user.role})
            </span>
            <button
              onClick={logout}
              className="text-sm bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded"
            >
              Log out
            </button>
          </>
        ) : (
          <Link
            href="/login"
            className="text-sm bg-indigo-600 hover:bg-indigo-500 px-3 py-1 rounded"
          >
            Log in
          </Link>
        )}
      </div>
    </nav>
  );
}
