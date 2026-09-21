"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Bell,
  ClipboardList,
  Command,
  Home,
  Landmark,
  Loader2,
  LogOut,
  MapPin,
  PlusCircle,
  Search,
  UserCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { Dropdown } from "@/components/ui/dropdown";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { useAuth } from "@/components/auth/auth-provider";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { LanguageSelector } from "@/components/ui/language-selector";
import { CommandPalette } from "@/components/layout/command-palette";
import { AssistantWidget } from "@/components/assistant/assistant-widget";
import { roleLabel } from "@/components/layout/nav-config";
import { initials } from "@/components/dashboard/format";

interface CitizenNavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
}

const CITIZEN_NAV: CitizenNavItem[] = [
  { label: "Home", href: "/dashboard", icon: Home, exact: true },
  { label: "My Complaints", href: "/dashboard/complaints", icon: ClipboardList },
  { label: "Notifications", href: "/dashboard/notifications", icon: Bell },
  { label: "Profile", href: "/dashboard/profile", icon: UserCircle },
];

function useActive(href: string, exact?: boolean): boolean {
  const pathname = usePathname();
  return exact ? pathname === href : pathname.startsWith(href);
}

function DesktopNavLink({ item }: { item: CitizenNavItem }) {
  const active = useActive(item.href, item.exact);
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        active ? "bg-primary-50 text-primary-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      )}
    >
      <item.icon className="h-4 w-4" />
      {item.label}
    </Link>
  );
}

function MobileNavItem({ item, onNavigate }: { item: CitizenNavItem; onNavigate?: () => void }) {
  const active = useActive(item.href, item.exact);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex flex-col items-center justify-center gap-0.5 rounded-xl px-1 py-1.5 text-[10px] font-medium transition-colors",
        active ? "text-primary-700" : "text-slate-500 hover:text-slate-800"
      )}
    >
      <item.icon className="h-5 w-5" />
      {item.label}
    </Link>
  );
}

export function CitizenShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [loggingOut, setLoggingOut] = React.useState(false);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const handleLogout = async () => {
    setLoggingOut(true);
    await logout();
  };

  const registeredWardName =
    user?.ward?.name ?? user?.ward?.code ?? null;

  return (
    <ProtectedRoute allow={["CITIZEN"]}>
      <div className="min-h-screen bg-canvas">
        {/* Top bar */}
        <header className="sticky top-0 z-40 border-b border-border-soft bg-surface/85 backdrop-blur-xl">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
            <Link href="/dashboard" className="flex min-w-0 items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-600 to-primary-800 text-white shadow-sm">
                <Landmark className="h-5 w-5" />
              </span>
              <span className="hidden min-w-0 flex-col leading-tight sm:flex">
                <span className="text-[15px] font-semibold tracking-tight text-slate-900">
                  CivicAgent
                </span>
                <span className="text-[10px] font-medium uppercase tracking-widest text-slate-400">
                  Citizen Portal
                </span>
              </span>
              {registeredWardName && (
                <span className="ml-1 hidden items-center gap-1 rounded-full border border-border-soft bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600 md:inline-flex">
                  <MapPin className="h-3 w-3 text-primary-600" />
                  {registeredWardName}
                </span>
              )}
            </Link>

            <nav
              className="hidden items-center gap-1 lg:flex"
              aria-label="Primary"
            >
              {CITIZEN_NAV.map((item) => (
                <DesktopNavLink key={item.href} item={item} />
              ))}
            </nav>

            <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
              <Link href="/report" className="hidden lg:inline-flex">
                <Button size="sm" className="gap-1.5 rounded-lg bg-primary-600 hover:bg-primary-700">
                  <PlusCircle className="h-4 w-4" />
                  Report
                </Button>
              </Link>
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                className="hidden items-center gap-2 rounded-lg border border-border-strong bg-slate-50 px-2.5 py-1.5 text-sm text-slate-400 transition-colors hover:border-slate-300 hover:text-slate-600 xl:flex"
                aria-label="Open command search"
              >
                <Search className="h-3.5 w-3.5" />
                <span className="pr-2">Search</span>
                <kbd className="flex items-center gap-0.5 rounded border border-border-strong bg-surface px-1 py-0.5 text-[10px] font-medium text-slate-400">
                  <Command className="h-2.5 w-2.5" />
                  K
                </kbd>
              </button>
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 xl:hidden"
                aria-label="Search"
              >
                <Search className="h-5 w-5" />
              </button>

              <div className="mx-1 hidden h-5 w-px bg-border-soft sm:block" />

              <NotificationBell allHref="/dashboard/notifications" />
              <LanguageSelector />
              <Dropdown
                align="right"
                trigger={
                  <button
                    type="button"
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
                header={
                  <div className="py-1">
                    <div className="text-sm font-medium text-slate-900">{user?.full_name}</div>
                    <div className="text-xs text-slate-500">{user?.email}</div>
                    <span className="mt-1.5 inline-flex rounded-full bg-primary-50 px-2 py-0.5 text-[11px] font-medium text-primary-700">
                      {roleLabel(user?.role.name)}
                    </span>
                  </div>
                }
                items={[
                  {
                    label: "Profile",
                    onClick: () => router.push("/dashboard/profile"),
                    icon: <UserCircle className="h-4 w-4" />,
                  },
                  {
                    label: loggingOut ? "Signing out…" : "Log out",
                    onClick: handleLogout,
                    icon: loggingOut ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <LogOut className="h-4 w-4" />
                    ),
                    destructive: true,
                    disabled: loggingOut,
                  },
                ]}
              />
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="mx-auto max-w-6xl px-4 pb-32 pt-6 sm:px-6 lg:pb-14 lg:pt-8">
          {children}
        </main>

        {/* Mobile bottom navigation */}
        <nav
          className="fixed inset-x-0 bottom-0 z-50 border-t border-border-soft bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-lg lg:hidden"
          aria-label="Mobile primary"
        >
          <div className="relative mx-auto grid max-w-md grid-cols-5">
            {CITIZEN_NAV.slice(0, 2).map((item) => (
              <div key={item.href} className="flex items-end justify-center">
                <MobileNavItem item={item} />
              </div>
            ))}

            <div className="flex items-end justify-center">
              <Link
                href="/report"
                aria-label="Report a civic issue"
                className="relative -top-5 flex h-14 w-14 items-center justify-center rounded-full border-4 border-canvas bg-gradient-to-br from-primary-600 to-primary-800 text-white shadow-lg shadow-primary-600/30 transition-transform hover:scale-105 active:scale-95"
              >
                <PlusCircle className="h-6 w-6" />
              </Link>
            </div>

            {CITIZEN_NAV.slice(2).map((item) => (
              <div key={item.href} className="flex items-end justify-center">
                <MobileNavItem item={item} />
              </div>
            ))}
          </div>
        </nav>

        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        <AssistantWidget />
      </div>
    </ProtectedRoute>
  );
}