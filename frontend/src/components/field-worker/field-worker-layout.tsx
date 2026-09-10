"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  CheckCircle2,
  HardHat,
  ListChecks,
  Loader2,
  LogOut,
  Navigation,
  UserRound,
  Wifi,
  WifiOff,
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

const NAV_ITEMS = [
  { href: "/work", label: "Jobs", icon: ListChecks, exact: true },
  { href: "/work/nearby", label: "Nearby", icon: Navigation, exact: false },
  { href: "/work/active", label: "Active", icon: Activity, exact: false },
  { href: "/work/completed", label: "Done", icon: CheckCircle2, exact: false },
  { href: "/work/profile", label: "Profile", icon: UserRound, exact: false },
];

export function FieldWorkerLayout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
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

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname.startsWith(href);

  const statusChip = (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        online ? "bg-success-500/15 text-success-300" : "bg-warning-500/15 text-warning-300"
      )}
    >
      {online ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
      {online ? "Online" : `Offline · ${pending} queued`}
    </span>
  );

  const accountMenu = (
    <Dropdown
      align="right"
      trigger={
        <button
          className="flex items-center gap-2 rounded-full p-0.5 transition-opacity hover:opacity-80"
          aria-label="Account menu"
        >
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
          label: "My Profile",
          onClick: () => router.push("/work/profile"),
          icon: <UserRound className="h-4 w-4" />,
        },
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
  );

  const navList = (
    <>
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active = isActive(item.href, item.exact);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            title={item.label}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-colors",
              active
                ? "bg-primary-600/90 text-white shadow-sm"
                : "text-slate-300 hover:bg-white/5 hover:text-white"
            )}
          >
            <Icon className={cn("h-[18px] w-[18px]", active ? "text-white" : "text-slate-400")} />
            {item.label}
          </Link>
        );
      })}
    </>
  );

  const mobileNav = (
    <nav
      className="lg:hidden fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border-soft bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-4px_20px_rgba(0,0,0,0.06)]"
      aria-label="Field work navigation"
    >
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active = isActive(item.href, item.exact);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-14 flex-col items-center justify-center gap-1 text-[10px] font-semibold transition-colors",
              active ? "text-primary-700" : "text-slate-400 hover:text-slate-700"
            )}
          >
            <span
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-full transition-colors",
                active ? "bg-primary-100 text-primary-700" : "text-slate-400"
              )}
            >
              <Icon className="h-[18px] w-[18px]" />
            </span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  const mobileHeader = (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-2 border-b border-white/10 bg-gradient-to-r from-navy-950 to-navy-900 px-3 text-white shadow-sm lg:hidden">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-warning-400 to-warning-600 text-white shadow-md">
          <HardHat className="h-5 w-5" />
        </div>
        <div className="min-w-0 leading-tight">
          <div className="text-sm font-semibold tracking-tight">Field Work</div>
          {statusChip}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {pending > 0 && (
          <span
            className="flex items-center gap-1 rounded-full bg-warning-500/20 px-2 py-0.5 text-[11px] font-semibold text-warning-200"
            title="Pending sync actions"
          >
            <ListChecks className="h-3 w-3" />
            {pending}
          </span>
        )}
        <NotificationBell />
        {accountMenu}
      </div>
    </header>
  );

  const desktopSidebar = (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-navy-800 bg-navy-950 text-white lg:flex">
      <div className="flex items-center gap-3 border-b border-white/10 bg-gradient-to-b from-navy-850 to-navy-950 px-5 py-5">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-warning-400 to-warning-600 text-white shadow-md">
          <HardHat className="h-5 w-5" />
        </div>
        <div className="min-w-0 leading-tight">
          <div className="text-sm font-semibold tracking-tight">Field Work</div>
          <div className="mt-1">{statusChip}</div>
        </div>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto px-3 py-4">{navList}</div>
      <div className="border-t border-white/10 p-3">
        <div className="flex items-center gap-3 rounded-xl bg-white/5 p-2.5">
          <Avatar
            size="sm"
            fallback={initials(user?.full_name)}
            src={user?.profile.avatar_url || undefined}
            alt={user?.full_name || "User"}
          />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-xs font-semibold">{user?.full_name || "Field Worker"}</div>
            <div className="truncate text-[11px] text-slate-400">{user?.email}</div>
          </div>
          <button
            onClick={handleLogout}
            disabled={loggingOut}
            className="rounded-lg p-2 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="Log out"
          >
            {loggingOut ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </aside>
  );

  return (
    <ProtectedRoute allow={["FIELD_WORKER"]}>
      <div className="min-h-screen bg-canvas lg:flex">
        {desktopSidebar}
        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          {mobileHeader}
          <main className="mx-auto w-full max-w-2xl flex-1 px-3 py-5 pb-28 sm:px-4 lg:px-6 lg:py-8 lg:pb-10">
            {children}
          </main>
        </div>
        {mobileNav}
      </div>
    </ProtectedRoute>
  );
}