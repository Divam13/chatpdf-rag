"use client";

import { createContext, useContext, useState, useEffect } from "react";
import { getMe, logout as apiLogout } from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const token = localStorage.getItem("token");

    if (!token) {
      return () => {
        active = false;
      };
    }

    getMe()
      .then((u) => {
        if (active) setUser(u);
      })
      .catch(() => {
        localStorage.removeItem("token");
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  function loginUser(userData, token) {
    localStorage.setItem("token", token);
    setUser(userData);
    setLoading(false);
  }

  function logoutUser() {
    apiLogout();
    localStorage.removeItem("token");
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, loginUser, logoutUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}