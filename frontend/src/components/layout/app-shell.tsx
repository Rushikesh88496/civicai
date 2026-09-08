"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  Menu,
  X,
  Search,
  LogOut,
  UserCircle,
  Loader2,
  Landmark,
  Command,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { Dropdown } from "@/components/ui/dropdown";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { useAuth } from "@/components/auth/auth-provider";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { LanguageSelector } from "@/components/ui/language-selector";
import { AssistantWidget } from "@/components/assistant/assistant-widget";
import { CommandPalette } from "@/components/layout/command-palette";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { getNavSections, roleLabel } from "@/components/layout/nav-config";
import { initials } from "@/components/dashboard/format";

type Role = "CITIZEN" | "OFFICER" | "WARD_REPRESENTATIVE" | "FIELD_WORKER" | "ADMIN" | "SUPER_ADMIN";

interface SidebarContentProps {
  role?: string;
  pathname: string;
  onNavigate?: () => void;
}

function SidebarContent({ role, pathname, onNavigate }: SidebarContentProps) {
  const { user, logout } = useAuth();
  const [loggingOut, setLoggingOut] = React.useState(false);
  const sections = getNavSections(role);

  const handleLogout = async () => {
    setLoggingOut(true);
    await logout();
  };

  return (
    <div className="flex h-full flex-col bg-navy-950 text-slate-300">
      {/* Brand */}
      <div className="flex h-16 items-center gap-2.5 border-b border-white/10 px-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-600 text-white shadow-sm">
          <Landmark className="h-5 w-5" />
        </span>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight text-white">
            CivicAgent
          </div>
          <div className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            {roleLabel(role)}
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-5" aria-label="Primary">
        {sections.map((section) => (
          <div key={section.label}>
            <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
              {section.label}
            </div>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = item.exact
                  ? pathname === item.href
                  : pathname.startsWith(item.href.split("?")[0]);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                        active
                          ? "bg-white/10 text-white"
                          : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
                      )}
                    >
                      {active && (
                        <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-primary-400" />
                      )}
                      <item.icon
                        className={cn(
                          "h-4 w-4 shrink-0",
                          active ? "text-primary-300" : "text-slate-500 group-hover:text-slate-300"
                        )}
                      />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* User footer */}
      <div className="border-t border-white/10 p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
          <Avatar
            size="sm"
            fallback={initials(user?.full_name)}
            src={user?.profile.avatar_url || undefined}
            alt={user?.full_name || "User"}
          />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-sm font-medium text-white">
              {user?.full_name}
            </div>
            <div className="truncate text-[11px] text-slate-400">
              {user?.email}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleLogout}
            aria-label="Log out"
            className="text-slate-400 hover:bg-white/10 hover:text-white"
          >
            {loggingOut ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

export interface AppShellProps {
  children: React.ReactNode;
  allow?: Role[];
  narrow?: boolean;
}

export function AppShell({ children, allow, narrow }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [loggingOut, setLoggingOut] = React.useState(false);
  const role = user?.role.name;

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

  return (
    <ProtectedRoute allow={allow}>
      <div className="min-h-screen bg-canvas">
        {/* Desktop sidebar */}
        <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 lg:block">
          <SidebarContent role={role} pathname={pathname} />
        </aside>

        {/* Mobile drawer */}
        <AnimatePresence>
          {mobileOpen && (
            <>
              <motion.div
                className="fixed inset-0 z-40 bg-navy-950/60 backdrop-blur-[2px] lg:hidden"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={() => setMobileOpen(false)}
              />
              <motion.aside
                className="fixed inset-y-0 left-0 z-50 w-72 lg:hidden"
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ type: "tween", duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="relative h-full">
                  <SidebarContent role={role} pathname={pathname} onNavigate={() => setMobileOpen(false)} />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="absolute right-3 top-4 text-slate-400 hover:bg-white/10 hover:text-white"
                    onClick={() => setMobileOpen(false)}
                    aria-label="Close menu"
                  >
                    <X className="h-5 w-5" />
                  </Button>
                </div>
              </motion.aside>
            </>
          )}
        </AnimatePresence>

        {/* Main column */}
        <div className="lg:pl-64">
          {/* Header */}
          <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b border-border-soft bg-surface/90 px-4 backdrop-blur-md sm:px-6">
            <div className="flex min-w-0 items-center gap-2">
              <button
                className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-100 lg:hidden"
                onClick={() => setMobileOpen(true)}
                aria-label="Open menu"
              >
                <Menu className="h-5 w-5" />
              </button>
              <Breadcrumbs />
            </div>

            <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
              <button
                onClick={() => setPaletteOpen(true)}
                className="hidden items-center gap-2 rounded-md border border-border-strong bg-slate-50 px-2.5 py-1.5 text-sm text-slate-400 transition-colors hover:border-slate-300 hover:text-slate-600 sm:flex"
                aria-label="Open command search"
              >
                <Search className="h-3.5 w-3.5" />
                <span className="pr-2">Search</span>
                <kbd className="flex items-center gap-0.5 rounded border border-border-strong bg-surface px-1 py-0.5 text-[10px] font-medium text-slate-400">
                  <Command className="h-2.5 w-2.5" />K
                </kbd>
              </button>
              <button
                onClick={() => setPaletteOpen(true)}
                className="rounded-md p-2 text-slate-500 transition-colors hover:bg-slate-100 sm:hidden"
                aria-label="Search"
              >
                <Search className="h-5 w-5" />
              </button>

              <div className="mx-1 hidden h-5 w-px bg-border-soft sm:block" />

              <NotificationBell />
              <LanguageSelector />
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
                header={
                  <div className="py-1">
                    <div className="text-sm font-medium text-slate-900">{user?.full_name}</div>
                    <div className="text-xs text-slate-500">{user?.email}</div>
                    <span className="mt-1.5 inline-flex rounded-full bg-primary-50 px-2 py-0.5 text-[11px] font-medium text-primary-700">
                      {roleLabel(role)}
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
          </header>

          <main className={cn("py-6 sm:py-8", narrow ? "" : "")}>
            <div
              className={cn(
                "mx-auto px-4 sm:px-6 lg:px-8",
                narrow ? "max-w-4xl" : "max-w-[1400px]"
              )}
            >
              {children}
            </div>
          </main>
        </div>

        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        {role === "CITIZEN" && <AssistantWidget />}
      </div>
    </ProtectedRoute>
  );
}