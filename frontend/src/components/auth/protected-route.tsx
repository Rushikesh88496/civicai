"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { LoadingState } from "@/components/ui/loading-state";

type Role = "CITIZEN" | "OFFICER" | "WARD_REPRESENTATIVE" | "FIELD_WORKER" | "ADMIN" | "SUPER_ADMIN";

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** Restrict to one of these roles. Omit to allow any authenticated role. */
  allow?: Role[];
}

export function ProtectedRoute({ children, allow }: ProtectedRouteProps) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (allow && allow.length > 0 && user.role && !allow.includes(user.role.name as Role)) {
      router.replace("/dashboard");
    }
  }, [isLoading, user, allow, router]);

  if (isLoading) {
    return <LoadingState message="Loading your session…" />;
  }

  if (!user) {
    return null;
  }

  if (allow && allow.length > 0 && user.role && !allow.includes(user.role.name as Role)) {
    return null;
  }

  return <>{children}</>;
}