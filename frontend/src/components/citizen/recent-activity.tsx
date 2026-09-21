"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, BellRing } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { useNotifications } from "@/hooks/use-notifications";
import { notificationLinkHref } from "@/lib/notification-api";
import { notificationVisual } from "@/components/notifications/notification-visuals";
import { timeAgo } from "@/components/dashboard/format";
import { cn } from "@/lib/utils";

export function RecentActivity({ limit = 5 }: { limit?: number }) {
  const router = useRouter();
  const { items, loading, error, markRead } = useNotifications();
  const visible = items.slice(0, limit);

  const open = (item: (typeof items)[number]) => {
    if (!item.is_read) markRead(item.id);
    router.push(notificationLinkHref(item, "/dashboard/notifications"));
  };

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">
          <BellRing className="h-5 w-5 text-primary-600" />
          Recent activity
        </CardTitle>
        <Link
          href="/dashboard/notifications"
          className="hidden shrink-0 items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700 sm:inline-flex"
        >
          View all
          <ArrowRight className="h-4 w-4" />
        </Link>
      </CardHeader>

      <CardContent className="flex-1 pt-3">
        {loading ? (
          <div className="space-y-3">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-14 w-full rounded-xl" />
            ))}
          </div>
        ) : error ? (
          <p className="px-1 py-6 text-sm text-slate-500">
            Activity could not be loaded.{" "}
            <span className="text-slate-400">{error}</span>
          </p>
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<BellRing className="h-8 w-8 text-slate-300" />}
            title="No activity yet"
            description="Updates about your complaints — priority changes, work orders and milestones — will show up here in realtime."
            className="py-8"
          />
        ) : (
          <ul className="space-y-1">
            {visible.map((item) => {
              const visual = notificationVisual(item.notification_type);
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => open(item)}
                    className={cn(
                      "flex w-full items-start gap-3 rounded-xl px-2 py-2.5 text-left transition-colors hover:bg-slate-50",
                      !item.is_read && "bg-primary-50/50"
                    )}
                  >
                    <span className={cn("mt-0.5 shrink-0", visual.tone)}>{visual.icon}</span>
                    <span className="min-w-0 flex-1">
                      <span
                        className={cn(
                          "block truncate text-sm",
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
      </CardContent>
    </Card>
  );
}