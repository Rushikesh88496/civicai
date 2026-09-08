"use client";

import * as React from "react";
import Link from "next/link";
import { Bell, CheckCheck, Loader2, MessageSquare, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchNotifications,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/lib/conversation-api";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { timeAgo } from "@/components/dashboard/format";

interface NotificationsPanelProps {
  onOpenComplaint: (complaintId: string) => void;
}

export function NotificationsPanel({ onOpenComplaint }: NotificationsPanelProps) {
  const [open, setOpen] = React.useState(false);
  const [items, setItems] = React.useState<NotificationItem[]>([]);
  const [unread, setUnread] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    let active = true;
    fetchUnreadCount()
      .then((data) => {
        if (active) setUnread(data.unread_count);
      })
      .catch(() => {
        // ignore transient failures; badge will retry on next tick
      });
    const timer = window.setInterval(() => {
      fetchUnreadCount()
        .then((data) => {
          if (active) setUnread(data.unread_count);
        })
        .catch(() => {
          // empty
        });
    }, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  React.useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchNotifications();
      setItems(data.items);
      setUnread(data.unread_count);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleToggle = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      await load();
    }
  };

  const handleOpenItem = async (item: NotificationItem) => {
    if (!item.complaint_id) return;
    if (!item.is_read) {
      try {
        await markNotificationRead(item.id);
        setUnread((u) => Math.max(0, u - 1));
      } catch {
        // still navigate; read state will reconcile on next load
      }
    }
    setOpen(false);
    onOpenComplaint(item.complaint_id);
  };

  const handleMarkAll = async () => {
    setBusy(true);
    try {
      await markAllNotificationsRead();
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnread(0);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Notifications"
        onClick={handleToggle}
        className="relative"
      >
        <Bell className="h-5 w-5 text-slate-600" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-danger-500 px-1 text-[10px] font-bold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[360px] max-w-[90vw] overflow-hidden rounded-lg border border-border-soft bg-surface shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-slate-500" />
              <span className="text-sm font-semibold text-slate-900">Notifications</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleMarkAll}
              disabled={busy || unread === 0}
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
            ) : items.length === 0 ? (
              <EmptyState
                icon={<Inbox className="h-8 w-8 text-slate-400" />}
                title="No notifications"
                description="Updates about your complaint conversations will appear here."
                className="py-8"
              />
            ) : (
              <ul className="divide-y divide-slate-100">
                {items.map((item) => (
                  <li key={item.id}>
                    <button
                      onClick={() => handleOpenItem(item)}
                      className={cn(
                        "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50",
                        !item.is_read && "bg-primary-50/60"
                      )}
                      disabled={!item.complaint_id}
                    >
                      <MessageSquare
                        className={cn(
                          "mt-0.5 h-4 w-4 shrink-0",
                          item.is_read ? "text-slate-300" : "text-primary-500"
                        )}
                      />
                      <span className="flex-1">
                        <span className="block text-sm text-slate-800">{item.body}</span>
                        <span className="mt-0.5 block text-xs text-slate-400">
                          {item.actor_name ? `${item.actor_name} · ` : ""}
                          {timeAgo(item.created_at)}
                        </span>
                      </span>
                      {!item.is_read && (
                        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary-500" />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-slate-100 px-4 py-2">
            <Link href="/messages" onClick={() => setOpen(false)} className={cn("text-xs font-medium text-primary-600 hover:underline")}>
              Open your messages
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}