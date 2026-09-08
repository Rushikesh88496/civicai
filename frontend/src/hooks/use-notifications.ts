"use client";

// Shared notification state for the Part 21 bell + full-page center.
//
// * Live unread badge: a per-user /ws/notifications connection pushes
//   `{type:"snapshot", unread_count}` anywhere a new notification arrives.
// * REST poll fallback: the backend also degrades to pub/sub-less operation,
//   so the badge re-syncs over HTTP every 30s (works even when Redis is down).
// * List state (page / unread filter / items / totals) fetched on demand.

import * as React from "react";
import {
  fetchNotifications,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
  notificationsWsUrl,
  type NotificationItem,
} from "@/lib/notification-api";
import { getAccessToken } from "@/lib/auth-api";

const POLL_INTERVAL_MS = 30_000;
const RECONNECT_DELAY_MS = 5_000;
const PAGE_SIZE = 20;

export interface UseNotificationsResult {
  items: NotificationItem[];
  total: number;
  unreadCount: number;
  loading: boolean;
  error: string | null;
  page: number;
  setPage: (page: number) => void;
  unreadOnly: boolean;
  setUnreadOnly: (value: boolean) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  reload: () => void;
}

export function useNotifications(): UseNotificationsResult {
  const [items, setItems] = React.useState<NotificationItem[]>([]);
  const [total, setTotal] = React.useState(0);
  const [unreadCount, setUnreadCount] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(1);
  const [unreadOnly, setUnreadOnly] = React.useState(false);
  const [version, setVersion] = React.useState(0);

  // Live badge: WebSocket + 30s REST fallback.
  React.useEffect(() => {
    let active = true;
    let ws: WebSocket | null = null;
    let closedByUs = false;
    let reconnectTimer: number | undefined;

    const syncUnread = () => {
      fetchUnreadCount()
        .then((data) => {
          if (active) setUnreadCount(data.unread_count);
        })
        .catch(() => {
          // transient; the badge retries on the next tick
        });
    };

    const connect = () => {
      getAccessToken()
        .then((token) => {
          if (!token || !active) return;
          const socket = new WebSocket(
            `${notificationsWsUrl()}?token=${encodeURIComponent(token)}`
          );
          ws = socket;
          socket.onmessage = (event) => {
            try {
              const message = JSON.parse(String(event.data)) as {
                type?: string;
                unread_count?: number;
              };
              if (
                message?.type === "snapshot" &&
                typeof message.unread_count === "number" &&
                active
              ) {
                setUnreadCount(message.unread_count);
              }
            } catch {
              // ignore malformed frames
            }
          };
          socket.onopen = () => syncUnread();
          socket.onerror = () => {
            try {
              socket.close();
            } catch {
              // ignore
            }
          };
          socket.onclose = () => {
            if (!active || closedByUs) return;
            reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
          };
        })
        .catch(() => {
          // auth unavailable; the REST poll keeps the badge fresh
        });
    };

    connect();
    syncUnread();
    const pollTimer = window.setInterval(syncUnread, POLL_INTERVAL_MS);

    return () => {
      active = false;
      closedByUs = true;
      try {
        ws?.close();
      } catch {
        // ignore
      }
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
    };
  }, []);

  // List state.
  React.useEffect(() => {
    let active = true;
    // Reset the view before the next fetch lands. setState on the microtask
    // avoids cascading renders from a synchronous call in the effect body.
    Promise.resolve().then(() => {
      if (!active) return;
      setLoading(true);
      setError(null);
      setItems([]);
    });
    fetchNotifications({ page, pageSize: PAGE_SIZE, unreadOnly })
      .then((data) => {
        if (!active) return;
        setItems(data.items);
        setTotal(data.total);
        setUnreadCount(data.unread_count);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load notifications.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, unreadOnly, version]);

  const markRead = React.useCallback(async (id: string) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, is_read: true } : item))
    );
    setUnreadCount((count) => Math.max(0, count - 1));
    try {
      await markNotificationRead(id);
    } catch {
      // read state will reconcile on the next poll/reload
    }
  }, []);

  const markAllRead = React.useCallback(async () => {
    setItems((prev) => prev.map((item) => ({ ...item, is_read: true })));
    setUnreadCount(0);
    try {
      await markAllNotificationsRead();
    } catch {
      // read state will reconcile on the next poll/reload
    }
  }, []);

  const reload = React.useCallback(() => setVersion((value) => value + 1), []);

  return {
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
  };
}