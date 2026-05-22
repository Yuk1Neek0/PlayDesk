"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

interface User {
  name: string;
  role: "customer" | "staff";
}

interface AuthContextValue {
  user: User | null;
  // false until the persisted session has been read from localStorage —
  // lets route guards avoid redirecting during the first render.
  ready: boolean;
  login: (name: string, role: "customer" | "staff") => void;
  logout: () => void;
}

const STORAGE_KEY = "playdesk.user";

const AuthContext = createContext<AuthContextValue>({
  user: null,
  ready: false,
  login: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  // Restore any persisted session once, on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setUser(JSON.parse(raw) as User);
    } catch {
      // ignore malformed/unavailable storage
    }
    setReady(true);
  }, []);

  function login(name: string, role: "customer" | "staff") {
    const next: User = { name, role };
    setUser(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore unavailable storage
    }
  }

  function logout() {
    setUser(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore unavailable storage
    }
  }

  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
