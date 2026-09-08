"use client";

import { NotificationCenter } from "@/components/notifications/notification-center";
import { AppShell } from "@/components/layout/app-shell";

export default function NotificationsPage() {
  return (
    <AppShell allow={["CITIZEN", "WARD_REPRESENTATIVE", "OFFICER", "ADMIN", "FIELD_WORKER"]}>
      <NotificationCenter />
    </AppShell>
  );
}