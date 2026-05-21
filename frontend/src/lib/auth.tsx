"use client";

import React, { createContext, useContext, useState } from "react";

interface User {
  name: string;
  role: "customer" | "staff";
}

interface AuthContextValue {
  user: User | null;
  login: (name: string, role: "customer" | "staff") => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  login: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  function login(name: string, role: "customer" | "staff") {
    setUser({ name, role });
  }

  function logout() {
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
