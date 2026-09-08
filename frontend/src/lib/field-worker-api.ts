"use client";

import { ApiError, getAccessToken } from "@/lib/auth-api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail[0]?.msg || "Invalid input.";
  } catch {
    // ignore parse errors
  }
  return res.statusText || "Request failed.";
}

async function authorizedFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return res.json() as Promise<T>;
}

// --------------------------------------------------------------------------- //
// Types (mirror the backend /worker schemas)
// --------------------------------------------------------------------------- //

export type WorkOrderStatusValue =
  | "PENDING_APPROVAL"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "CLOSED"
  | "REJECTED"
  | "ESCALATED";

export interface WorkerJob {
  id: string;
  complaint_id: string;
  incident?: string | null;
  department: string;
  priority?: string | null;
  status: WorkOrderStatusValue;
  address?: string | null;
  location_lat?: number | null;
  location_lon?: number | null;
  due_at?: string | null;
  eta_minutes?: number | null;
  distance_m?: number | null;
  accepted_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  worker_notes?: string | null;
  has_before_photo: boolean;
  has_after_photo: boolean;
  sla_state?: "ON_TRACK" | "AT_RISK" | "BREACHED" | "COMPLETED";
  sla_progress?: number;
  sla_remaining_seconds?: number | null;
  sla_remaining_human?: string | null;
}

export interface WorkerDashboard {
  assigned: WorkerJob[];
  nearby: WorkerJob[];
  p1: WorkerJob[];
  completed: WorkerJob[];
}

export interface WorkOrderPhoto {
  id: string;
  category: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  allowed: boolean;
  url?: string;
  created_at: string;
}

export interface WorkOrderActivity {
  id: string;
  activity_type: string;
  note?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  geo_denied: boolean;
  media_id?: string | null;
  worker_name?: string | null;
  recorded_at: string;
}

export interface WorkerOrderDetail {
  work_order: WorkerJob;
  complaint_id: string;
  complaint_title?: string | null;
  complaint_description?: string | null;
  complaint_status?: string | null;
  photos: WorkOrderPhoto[];
  activities: WorkOrderActivity[];
  status_history: Array<{
    action: string;
    note?: string | null;
    recorded_at: string;
  }>;
}

// --------------------------------------------------------------------------- //
// Dashboard + detail
// --------------------------------------------------------------------------- //

export async function fetchWorkerDashboard(
  lat?: number | null,
  lon?: number | null
): Promise<WorkerDashboard> {
  const qs = new URLSearchParams();
  if (lat != null) qs.set("latitude", String(lat));
  if (lon != null) qs.set("longitude", String(lon));
  const q = qs.toString();
  return authorizedFetch<WorkerDashboard>(
    `/api/v1/worker/dashboard${q ? `?${q}` : ""}`
  );
}

export async function fetchWorkerOrderDetail(
  orderId: string
): Promise<WorkerOrderDetail> {
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}`
  );
}

// --------------------------------------------------------------------------- //
// Resolution verification (Part 19) — read-only for the assigned worker
// --------------------------------------------------------------------------- //

export interface WorkerVerification {
  id: string;
  work_order_id: string;
  complaint_id: string;
  before_url: string;
  after_url: string;
  repair_evidence: string | null;
  remaining_issue: string | null;
  confidence: number;
  verification_status:
    | "VERIFIED"
    | "PARTIALLY_RESOLVED"
    | "NOT_RESOLVED"
    | "NEEDS_HUMAN_REVIEW";
  human_review_required: boolean;
  source: "groq" | "pixel-diff";
  review_note: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export async function fetchWorkerVerification(
  orderId: string
): Promise<WorkerVerification | null> {
  return authorizedFetch<WorkerVerification | null>(
    `/api/v1/work-orders/${orderId}/verification`
  );
}

// --------------------------------------------------------------------------- //
// Workflow actions (idempotent via client_ref)
// --------------------------------------------------------------------------- //

export interface WorkerActionPayload {
  note?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  geo_denied?: boolean;
  client_ref: string;
}

export async function acceptJob(
  orderId: string,
  payload: WorkerActionPayload
): Promise<WorkerOrderDetail> {
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}/accept`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export async function checkIn(
  orderId: string,
  activityType: "EN_ROUTE" | "ARRIVED",
  payload: WorkerActionPayload
): Promise<WorkerOrderDetail> {
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}/check-in`,
    { method: "POST", body: JSON.stringify({ activity_type: activityType, ...payload }) }
  );
}

export async function startJob(
  orderId: string,
  payload: WorkerActionPayload
): Promise<WorkerOrderDetail> {
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}/start`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export async function saveWorkerNotes(
  orderId: string,
  notes: string,
  clientRef: string
): Promise<WorkerOrderDetail> {
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}/notes`,
    { method: "POST", body: JSON.stringify({ notes, client_ref: clientRef }) }
  );
}

export async function uploadWorkOrderPhoto(
  orderId: string,
  file: File,
  category: "BEFORE" | "AFTER",
  fields: { client_ref: string; latitude?: number | null; longitude?: number | null; geo_denied?: boolean }
): Promise<WorkerOrderDetail> {
  const form = new FormData();
  form.append("category", category);
  form.append("file", file, file.name || "photo.jpg");
  form.append("client_ref", fields.client_ref);
  if (fields.latitude != null) form.append("latitude", String(fields.latitude));
  if (fields.longitude != null) form.append("longitude", String(fields.longitude));
  form.append("geo_denied", String(fields.geo_denied ?? false));
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}/photos`,
    { method: "POST", body: form }
  );
}

export async function completeJob(
  orderId: string,
  payload: WorkerActionPayload
): Promise<WorkerOrderDetail> {
  return authorizedFetch<WorkerOrderDetail>(
    `/api/v1/worker/orders/${orderId}/complete`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}