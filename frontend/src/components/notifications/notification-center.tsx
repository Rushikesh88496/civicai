"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { notificationLinkHref, type NotificationItem } from "@/lib/notification-api";
import { useNotifications } from "@/hooks/use-notifications";
import { notificationVisual } from "@/components/notifications/notification-visuals";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Pagination } from "@/components/ui/pagination";
import { timeAgo } from "@/components/dashboard/format";

const PAGE_SIZE = 20;

export function NotificationCenter() {
  const router = useRouter();
  const {
    items,
    total,
    unreadCount,
    loading,
    error,
    page,
    setPage,
    unreadOnly,
    setUnreadOnly,
    markRead,
    markAllRead,
    reload,
  } = useNotifications();

  const [busy, setBusy] = React.useState(false);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleOpenItem = (item: NotificationItem) => {
    if (!item.is_read) markRead(item.id);
    router.push(notificationLinkHref(item));
  };

  const handleMarkAll = async () => {
    setBusy(true);
    try {
      await markAllRead();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">Notifications</h1>
        <p className="text-slate-500">
          {unreadCount > 0
            ? `${unreadCount} unread · updates about your complaints, work orders and conversations.`
            : "You're all caught up."}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center rounded-lg border border-border-soft bg-surface p-0.5">
          <button
            onClick={() => setUnreadOnly(false)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              !unreadOnly ? "bg-primary-600 text-white" : "text-slate-600 hover:text-slate-900"
            )}
          >
            All
          </button>
          <button
            onClick={() => setUnreadOnly(true)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              unreadOnly ? "bg-primary-600 text-white" : "text-slate-600 hover:text-slate-900"
            )}
          >
            Unread {unreadCount > 0 ? `(${unreadCount})` : ""}
          </button>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleMarkAll()}
          disabled={busy || unreadCount === 0}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <CheckCheck className="h-4 w-4" />
          )}
          Mark all read
        </Button>
      </div>

      {error ? (
        <ErrorState
          title="Could not load notifications"
          description={error}
          action={
            <Button onClick={reload} variant="outline">
              Try Again
            </Button>
          }
        />
      ) : loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <div className="p-10">
            <EmptyState
              icon={<Bell className="h-10 w-10 text-slate-300" />}
              title={unreadOnly ? "No unread notifications" : "No notifications yet"}
              description={
                unreadOnly
                  ? "You've read everything in this view."
                  : "Updates about your complaints and work orders will appear here."
              }
            />
          </div>
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const visual = notificationVisual(item.notification_type);
            return (
              <Card
                key={item.id}
                className="overflow-hidden rounded-2xl shadow-card transition-shadow hover:shadow-card-hover"
              >
                <button
                  onClick={() => handleOpenItem(item)}
                  className={cn(
                    "flex w-full items-start gap-4 p-4 text-left transition-colors",
                    item.is_read ? "hover:bg-slate-50" : "border-l-4 border-l-primary-500 bg-primary-50/40 hover:bg-primary-50/70"
                  )}
                >
                  <span
                    className={cn(
                      "shrink-0 rounded-xl p-2",
                      item.is_read ? "bg-slate-50" : "bg-white",
                      visual.tone
                    )}
                  >
                    {visual.icon}
                  </span>
                  <span className="flex-1">
                    <span
                      className={cn(
                        "block text-sm",
                        item.is_read ? "text-slate-800" : "font-semibold text-slate-900"
                      )}
                    >
                      {item.title || item.notification_type}
                    </span>
                    {item.body && (
                      <span className="mt-0.5 block text-sm text-slate-500">{item.body}</span>
                    )}
                    <span className="mt-1 block text-xs text-slate-400">
                      {item.actor_name ? `${item.actor_name} · ` : ""}
                      {timeAgo(item.created_at)}
                    </span>
                  </span>
                  {!item.is_read && (
                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary-500" />
                  )}
                </button>
              </Card>
            );
          })}
        </div>
      )}

      {!loading && !error && (
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          onPageChange={setPage}
          className="pt-2"
        />
      )}
    </div>
  );
}