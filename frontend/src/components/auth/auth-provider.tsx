"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  type AuthUser,
  clearSession,
  fetchMe,
  getStoredRefreshToken,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
} from "@/lib/auth-api";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (fullName: string, email: string, password: string, wardId: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = React.useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    async function restoreSession() {
      // Only attempt to restore if we have a stored refresh token.
      if (!getStoredRefreshToken()) {
        setIsLoading(false);
        return;
      }
      try {
        const me = await fetchMe();
        if (active) setUser(me);
      } catch {
        clearSession();
        if (active) setUser(null);
      } finally {
        if (active) setIsLoading(false);
      }
    }
    restoreSession();
    return () => {
      active = false;
    };
  }, []);

  const login = React.useCallback(async (email: string, password: string) => {
    const me = await apiLogin(email, password);
    setUser(me);
    return me;
  }, []);

  const register = React.useCallback(
    async (fullName: string, email: string, password: string, wardId: string) => {
      const me = await apiRegister(fullName, email, password, wardId);
      setUser(me);
      return me;
    },
    []
  );

  const logout = React.useCallback(async () => {
    await apiLogout();
    setUser(null);
    router.replace("/login");
  }, [router]);

  const refreshUser = React.useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
  }, []);

  const value = React.useMemo(
    () => ({
      user,
      isLoading,
      isAuthenticated: user !== null,
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, isLoading, login, register, logout, refreshUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider.");
  }
  return ctx;
}