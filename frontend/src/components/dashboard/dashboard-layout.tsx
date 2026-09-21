"use client";

import { CitizenShell } from "@/components/citizen/citizen-shell";

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <CitizenShell>{children}</CitizenShell>;
}