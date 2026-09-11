"use client";

import { AppShell } from "@/components/layout/app-shell";

export function OfficerLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell allow={["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"]}>
      {children}
    </AppShell>
  );
}