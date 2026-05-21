"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();

  function handleLogin(name: string, role: "customer" | "staff") {
    login(name, role);
    router.push("/");
  }

  return (
    <div className="max-w-md mx-auto px-4 py-16">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Sign In</h1>
      <p className="text-gray-500 mb-8">
        One-click demo login — no passwords required.
      </p>

      <div className="bg-white rounded-lg shadow p-6 space-y-4">
        <p className="text-sm font-medium text-gray-600 mb-2">Continue as:</p>

        <button
          onClick={() => handleLogin("Guest Customer", "customer")}
          className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-3 rounded-lg font-medium transition"
        >
          Customer (Guest)
        </button>

        <button
          onClick={() => handleLogin("Staff Member", "staff")}
          className="w-full bg-gray-800 hover:bg-gray-700 text-white py-3 rounded-lg font-medium transition"
        >
          Staff / Admin
        </button>

        <p className="text-xs text-gray-400 text-center pt-2">
          Dummy auth for demo purposes — real NextAuth integration in Wave 1.
        </p>
      </div>
    </div>
  );
}
