"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bell, CheckCheck, Loader2, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import { notificationLinkHref, type NotificationItem } from "@/lib/notification-api";
import { useNotifications } from "@/hooks/use-notifications";
import { notificationVisual } from "@/components/notifications/notification-visuals";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { timeAgo } from "@/components/dashboard/format";

interface NotificationBellProps {
  onNavigate?: (href: string) => void;
  /** Where the "View all" footer resolves to. Defaults to /notifications. */
  allHref?: string;
}

export function NotificationBell({ onNavigate, allHref = "/notifications" }: NotificationBellProps) {
  const router = useRouter();
  const { items, unreadCount, loading, markRead, markAllRead } = useNotifications();
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const go = (item: NotificationItem) => {
    const href = notificationLinkHref(item);
    setOpen(false);
    if (onNavigate) {
      onNavigate(href);
    } else {
      router.push(href);
    }
  };

  const handleOpenItem = (item: NotificationItem) => {
    if (!item.is_read) markRead(item.id);
    go(item);
  };

  const handleMarkAll = async () => {
    setBusy(true);
    try {
      await markAllRead();
    } finally {
      setBusy(false);
    }
  };

  const visibleItems = items.slice(0, 8);

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Notifications"
        onClick={() => setOpen((value) => !value)}
        className="relative"
      >
        <Bell className="h-5 w-5 text-slate-600" />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-danger-500 px-1 text-[10px] font-bold text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[360px] max-w-[90vw] overflow-hidden rounded-lg border border-border-soft bg-surface shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-slate-500" />
              <span className="text-sm font-semibold text-slate-900">Notifications</span>
              {unreadCount > 0 && (
                <span className="rounded-full bg-danger-100 px-2 py-0.5 text-xs font-semibold text-danger-700">
                  {unreadCount} unread
                </span>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void handleMarkAll()}
              disabled={busy || unreadCount === 0}
              className="text-xs"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCheck className="h-3.5 w-3.5" />
              )}
              Mark all read
            </Button>
          </div>

          <div className="max-h-[360px] overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading…
              </div>
            ) : visibleItems.length === 0 ? (
              <EmptyState
                icon={<Inbox className="h-8 w-8 text-slate-400" />}
                title="All caught up"
                description="New complaint and work-order updates will appear here."
                className="py-8"
              />
            ) : (
              <ul className="divide-y divide-slate-100">
                {visibleItems.map((item) => {
                  const visual = notificationVisual(item.notification_type);
                  return (
                    <li key={item.id}>
                      <button
                        onClick={() => handleOpenItem(item)}
                        className={cn(
                          "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50",
                          !item.is_read && "bg-primary-50/60"
                        )}
                      >
                        <span className={cn("mt-0.5 shrink-0", visual.tone)}>
                          {visual.icon}
                        </span>
                        <span className="flex-1">
                          <span
                            className={cn(
                              "block text-sm",
                              item.is_read ? "text-slate-700" : "font-semibold text-slate-900"
                            )}
                          >
                            {item.title || item.body}
                          </span>
                          <span className="mt-0.5 block text-xs text-slate-400">
                            {timeAgo(item.created_at)}
                          </span>
                        </span>
                        {!item.is_read && (
                          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary-500" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="border-t border-slate-100 px-4 py-2">
            <Link
              href={allHref}
              onClick={() => setOpen(false)}
              className="text-xs font-medium text-primary-600 hover:underline"
            >
              View all notifications
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}