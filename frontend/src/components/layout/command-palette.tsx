"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft, X } from "lucide-react";
import { getNavSections, type NavItem } from "@/components/layout/nav-config";
import { useAuth } from "@/components/auth/auth-provider";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const { user } = useAuth();
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [activeIndex, setActiveIndex] = React.useState(0);

  const items = React.useMemo(() => {
    const sections = getNavSections(user?.role.name);
    const flat: { item: NavItem; section: string }[] = [];
    for (const section of sections) {
      for (const item of section.items) flat.push({ item, section: section.label });
    }
    return flat;
  }, [user?.role.name]);

  const filtered = React.useMemo(() => {
    if (!query.trim()) return items;
    const q = query.trim().toLowerCase();
    return items.filter(
      ({ item, section }) =>
        item.label.toLowerCase().includes(q) ||
        item.description?.toLowerCase().includes(q) ||
        section.toLowerCase().includes(q)
    );
  }, [items, query]);

  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      }
      if (e.key === "Enter" && filtered[activeIndex]) {
        e.preventDefault();
        router.push(filtered[activeIndex].item.href);
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, filtered, activeIndex, onClose, router]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center pt-[14vh] backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label="Command search"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border-soft bg-surface shadow-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border-soft px-4">
          <Search className="h-4 w-4 shrink-0 text-slate-400" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            placeholder="Search pages, dashboards, reports…"
            className="h-12 w-full bg-transparent text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
          />
          <kbd className="hidden rounded border border-border-strong bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 sm:block">
            ESC
          </kbd>
        </div>
        <div className="max-h-[48vh] overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <p className="px-3 py-8 text-center text-sm text-slate-500">
              No matches for “{query}”.
            </p>
          ) : (
            filtered.map(({ item, section }, index) => (
              <button
                key={item.href}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => {
                  router.push(item.href);
                  onClose();
                }}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
                  index === activeIndex ? "bg-primary-50" : ""
                }`}
              >
                <span
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
                    index === activeIndex ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  <item.icon className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-slate-900">
                    {item.label}
                  </span>
                  {item.description && (
                    <span className="block truncate text-xs text-slate-500">
                      {item.description}
                    </span>
                  )}
                </span>
                <span className="hidden shrink-0 items-center gap-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400 sm:flex">
                  {section}
                  {index === activeIndex && <CornerDownLeft className="ml-1 h-3 w-3" />}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
      <button
        className="fixed right-4 top-4 rounded-lg border border-border-soft bg-surface p-2 text-slate-500 shadow-card transition-colors hover:text-slate-800"
        onClick={onClose}
        aria-label="Close search"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}