"use client";

import { Shield } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";

export function MessagesLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell allow={["CITIZEN", "WARD_REPRESENTATIVE", "OFFICER", "ADMIN", "FIELD_WORKER"]}>
      {children}
      <footer className="mt-8 border-t border-border-soft py-6">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-2 px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Shield className="h-4 w-4" />
            CivicAgent · Secure conversation channel
          </div>
          <div className="text-xs text-slate-400">
            AI drafts are suggestions shown for review and are never sent automatically.
          </div>
        </div>
      </footer>
    </AppShell>
  );
}