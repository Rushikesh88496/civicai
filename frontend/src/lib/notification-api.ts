"use client";

// Client-side helpers for the Part 21 centralized notification system.
// Canonical home for notification types + API calls. The Part 17
// conversation module re-exports these so legacy imports keep working.
// Reuses the access-token machinery from auth-api (in-memory access token +
// transparent refresh) so notifications are only ever fetched for the
// authenticated user.

import { authorizedFetch } from "@/lib/auth-api";

async function authorized<T>(path: string, init: RequestInit = {}): Promise<T> {
  return authorizedFetch<T>(path, init);
}

// --------------------------------------------------------------------------- //
// Types (mirror the backend /notifications schema)
// --------------------------------------------------------------------------- //

export interface NotificationItem {
  id: string;
  notification_type: string;
  title: string | null;
  body: string;
  link: string | null;
  channel: string | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
  complaint_id: string | null;
  work_order_id: string | null;
  message_id: string | null;
  actor_name: string | null;
  payload: Record<string, unknown> | null;
}

export interface NotificationListOut {
  items: NotificationItem[];
  unread_count: number;
  total: number;
  page: number;
  page_size: number;
}

export interface UnreadCountOut {
  unread_count: number;
}

export interface AcknowledgeOut {
  ok: boolean;
}

export interface NotificationListParams {
  page?: number;
  pageSize?: number;
  unreadOnly?: boolean;
}

// --------------------------------------------------------------------------- //
// API
// --------------------------------------------------------------------------- //

export async function fetchNotifications(
  params: NotificationListParams = {}
): Promise<NotificationListOut> {
  const query = new URLSearchParams();
  if (params.page && params.page > 1) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.unreadOnly) query.set("unread_only", "true");
  const qs = query.toString() ? `?${query.toString()}` : "";
  return authorized<NotificationListOut>(`/api/v1/notifications${qs}`);
}

export async function fetchUnreadCount(): Promise<UnreadCountOut> {
  return authorized<UnreadCountOut>("/api/v1/notifications/unread-count");
}

export async function markNotificationRead(
  notificationId: string
): Promise<NotificationItem> {
  return authorized<NotificationItem>(
    `/api/v1/notifications/${notificationId}/read`,
    { method: "POST" }
  );
}

export async function markAllNotificationsRead(): Promise<AcknowledgeOut> {
  return authorized<AcknowledgeOut>("/api/v1/notifications/read-all", {
    method: "POST",
  });
}

// --------------------------------------------------------------------------- //
// Realtime
// --------------------------------------------------------------------------- //

export function notificationsWsUrl(): string {
  // Token is appended later by the caller (getAccessToken is async); the ws
  // scheme depends on whether the frontend talks to localhost over http.
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const host = base.replace(/^https?:\/\//, "");
  const scheme = base.startsWith("https") ? "wss" : "ws";
  return `${scheme}://${host}/ws/notifications`;
}

// --------------------------------------------------------------------------- //
// Navigation
// --------------------------------------------------------------------------- //

/** Map a backend deep link to a route that exists in this frontend.
 *
 * Backend links like /officer/work-orders/{id} have no dedicated officer
 * detail route here, so staff land on the command center instead; messages
 * resolve to the ?complaint= view of /messages. Never returns an off-app or
 * protocol-relative URL.
 */
export function notificationLinkHref(
  item: Pick<NotificationItem, "link" | "complaint_id" | "work_order_id">,
  fallback = "/notifications"
): string {
  const link = item.link ?? null;
  if (link && link.startsWith("/") && !link.startsWith("//")) {
    const parts = link.split("/").filter(Boolean);
    const [root, ...rest] = parts;
    if (root === "work") return link;
    if (root === "dashboard") return link;
    if (root === "messages") {
      const complaintId = rest[0] ?? item.complaint_id ?? "";
      return complaintId ? `/messages?complaint=${complaintId}` : "/messages";
    }
    if (root === "officer") return "/officer";
    if (root === "ward-rep") return "/ward-rep";
    if (root === "notifications") return "/notifications";
  }
  return fallback;
}