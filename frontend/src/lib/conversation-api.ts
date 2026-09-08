"use client";

// Client-side helpers for the Part 17 CIVIC COMMUNICATION feature (secure
// complaint conversations, attachments, read receipts and in-app notifications).
// Reuses the access-token machinery from auth-api (in-memory access token +
// transparent refresh) so conversations are only ever populated for the
// authenticated participant.

import { ApiError, getAccessToken } from "@/lib/auth-api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail[0]?.msg || "Invalid input.";
    }
  } catch {
    // ignore parse errors
  }
  return res.statusText || "Request failed.";
}

// --------------------------------------------------------------------------- //
// Types (mirror the backend /conversations and /notifications schemas)
// --------------------------------------------------------------------------- //

export interface ConversationAttachment {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  url: string | null;
  created_at: string;
}

export interface MessageReadReceipt {
  user_id: string;
  user_name: string | null;
  read_at: string;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  complaint_id: string;
  author_id: string;
  author_name: string | null;
  role: string;
  body: string;
  created_at: string;
  attachments: ConversationAttachment[];
  read_by: MessageReadReceipt[];
  read_by_all: boolean;
  is_read_by_me: boolean;
}

export interface ConversationThread {
  complaint_id: string;
  complaint_title: string;
  complaint_status: string | null;
  messages: ConversationMessage[];
}

export interface ConversationListItem {
  complaint_id: string;
  complaint_title: string;
  complaint_status: string | null;
  last_message: string | null;
  last_message_at: string | null;
  last_author_name: string | null;
  unread_count: number;
}

export interface ConversationListOut {
  items: ConversationListItem[];
}

export interface AiDraft {
  summary: string;
  suggested_reply: string;
  draft: boolean;
  generated_by: string;
}

// --------------------------------------------------------------------------- //
// Authenticated transport (JSON + multipart)
// --------------------------------------------------------------------------- //

async function authorized<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const isJson = init?.body !== undefined && !(init.body instanceof FormData);
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(isJson ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// --------------------------------------------------------------------------- //
// Conversations
// --------------------------------------------------------------------------- //

export async function fetchConversations(): Promise<ConversationListOut> {
  return authorized<ConversationListOut>("/api/v1/conversations");
}

export async function fetchConversation(
  complaintId: string
): Promise<ConversationThread> {
  return authorized<ConversationThread>(
    `/api/v1/conversations/complaints/${complaintId}`
  );
}

export async function sendMessage(
  complaintId: string,
  body: string,
  attachmentIds: string[] = []
): Promise<ConversationThread> {
  return authorized<ConversationThread>(
    `/api/v1/conversations/complaints/${complaintId}/messages`,
    { method: "POST", body: JSON.stringify({ body, attachment_ids: attachmentIds }) }
  );
}

export async function uploadAttachment(
  complaintId: string,
  file: File
): Promise<ConversationAttachment> {
  const form = new FormData();
  form.append("file", file);
  return authorized<ConversationAttachment>(
    `/api/v1/conversations/complaints/${complaintId}/attachments`,
    { method: "POST", body: form }
  );
}

export async function markConversationRead(
  complaintId: string
): Promise<ConversationThread> {
  return authorized<ConversationThread>(
    `/api/v1/conversations/complaints/${complaintId}/read`,
    { method: "POST" }
  );
}

export async function fetchAiSummary(
  complaintId: string
): Promise<AiDraft> {
  return authorized<AiDraft>(
    `/api/v1/conversations/complaints/${complaintId}/ai-summary`,
    { method: "POST" }
  );
}

// --------------------------------------------------------------------------- //
// Notifications (canonical implementation lives in notification-api.ts)
// --------------------------------------------------------------------------- //

export {
  fetchNotifications,
  fetchUnreadCount,
  markNotificationRead,
  markAllNotificationsRead,
  notificationsWsUrl,
  notificationLinkHref,
} from "./notification-api";

export type {
  NotificationItem,
  NotificationListOut,
  NotificationListParams,
  UnreadCountOut,
  AcknowledgeOut,
} from "./notification-api";