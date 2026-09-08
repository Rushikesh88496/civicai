"use client";

import { AppShell } from "@/components/layout/app-shell";

export function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell allow={["SUPER_ADMIN"]}>
      {children}
    </AppShell>
  );
}