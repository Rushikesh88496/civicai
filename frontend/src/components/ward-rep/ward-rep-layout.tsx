"use client";

import { AppShell } from "@/components/layout/app-shell";

export function WardRepLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell allow={["WARD_REPRESENTATIVE", "OFFICER", "ADMIN"]}>
      {children}
    </AppShell>
  );
}