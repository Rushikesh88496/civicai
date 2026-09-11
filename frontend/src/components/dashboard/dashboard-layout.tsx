"use client";

import { AppShell } from "@/components/layout/app-shell";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell allow={["CITIZEN"]} narrow>
      {children}
    </AppShell>
  );
}