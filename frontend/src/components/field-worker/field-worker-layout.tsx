"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LogOut,
  Loader2,
  MapPin,
  CheckCircle2,
  Wifi,
  WifiOff,
  ListChecks,
  HardHat,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { useAuth } from "@/components/auth/auth-provider";
import { Dropdown } from "@/components/ui/dropdown";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { initials } from "@/components/dashboard/format";
import {
  pendingCount,
  processQueue,
  onQueueChanged,
  isOnline,
} from "@/lib/offline-queue";

const navItems = [
  { href: "/work", label: "Jobs", icon: <ListChecks className="h-5 w-5" /> },
  { href: "/work/nearby", label: "Nearby", icon: <MapPin className="h-5 w-5" /> },
  { href: "/work/completed", label: "Done", icon: <CheckCircle2 className="h-5 w-5" /> },
];

export function FieldWorkerLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [loggingOut, setLoggingOut] = React.useState(false);
  const [online, setOnline] = React.useState(isOnline());
  const [pending, setPending] = React.useState(() => pendingCount());

  React.useEffect(() => {
    const unsubscribe = onQueueChanged(setPending);
    const handleOnline = () => {
      setOnline(true);
      void processQueue();
    };
    const handleOffline = () => setOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    if (isOnline()) void processQueue();
    return () => {
      unsubscribe();
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const handleLogout = async () => {
    setLoggingOut(true);
    await logout();
  };

  const isActive = (href: string) =>
    href === "/work" ? pathname === "/work" : pathname.startsWith(href);

  return (
    <ProtectedRoute allow={["FIELD_WORKER"]}>
      <div className="min-h-screen bg-canvas pb-16">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-2 border-b border-border-soft bg-navy-950 px-4 text-white">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-warning-500 text-white">
              <HardHat className="h-5 w-5" />
            </div>
            <div className="min-w-0 leading-tight">
              <div className="text-sm font-semibold tracking-tight">Field Work</div>
              <div className="flex items-center gap-1 text-[11px] text-slate-300">
                {online ? (
                  <span className="flex items-center gap-0.5 text-success-300">
                    <Wifi className="h-3 w-3" /> Online
                  </span>
                ) : (
                  <span className="flex items-center gap-0.5 text-warning-300">
                    <WifiOff className="h-3 w-3" /> Offline · queued {pending}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {pending > 0 && (
              <span
                className="flex items-center gap-1 rounded-full bg-warning-500/20 px-2.5 py-1 text-xs font-semibold text-warning-200"
                title="Pending sync actions"
              >
                <ListChecks className="h-3.5 w-3.5" />
                {pending}
              </span>
            )}
            <NotificationBell />
            <Dropdown
              align="right"
              trigger={
                <button className="flex items-center gap-2 rounded-full p-0.5 transition-opacity hover:opacity-80" aria-label="Account menu">
                  <Avatar
                    size="sm"
                    fallback={initials(user?.full_name)}
                    src={user?.profile.avatar_url || undefined}
                    alt={user?.full_name || "User"}
                  />
                </button>
              }
              items={[
                { label: user?.full_name || "Account", onClick: () => {} },
                {
                  label: "Log out",
                  onClick: handleLogout,
                  icon: loggingOut ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <LogOut className="h-4 w-4" />
                  ),
                  destructive: true,
                },
              ]}
            />
          </div>
        </header>

        <main className="mx-auto max-w-2xl px-3 py-4 sm:px-4">{children}</main>

        <nav
          className="fixed inset-x-0 bottom-0 z-30 border-t border-border-soft bg-surface pb-[env(safe-area-inset-bottom)] shadow-card"
          aria-label="Field work navigation"
        >
          <div className="mx-auto grid max-w-2xl grid-cols-3">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive(item.href) ? "page" : undefined}
                className={cn(
                  "flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors",
                  isActive(item.href)
                    ? "text-primary-600"
                    : "text-slate-400 hover:text-slate-700"
                )}
              >
                {item.icon}
                {item.label}
              </Link>
            ))}
          </div>
        </nav>
      </div>
    </ProtectedRoute>
  );
}