"use client";

import { ApiError, getAccessToken } from "@/lib/auth-api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // ignore parse errors
  }
  return res.statusText || "Request failed.";
}

async function authorizedJson<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return res.json() as Promise<T>;
}

// --------------------------------------------------------------------------- //
// Types (mirror the backend /ward-rep schemas)
// --------------------------------------------------------------------------- //

export interface WardRepKpis {
  total_complaints: number;
  open: number;
  critical: number;
  resolved: number;
  sla_breaches: number;
}

export interface Representative {
  name?: string | null;
  email?: string | null;
  title?: string | null;
}

export interface WardRep {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  representative?: Representative | null;
}

export interface WardDashboard {
  ward?: WardRep | null;
  representative?: Representative | null;
  kpis: WardRepKpis;
}

export interface WardMapComplaint {
  id: string;
  complaint_id: string;
  title: string;
  status: string;
  priority?: string | null;
  department?: string | null;
  category?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  created_at: string;
}

export interface WardMapWorkOrder {
  id: string;
  complaint_id: string;
  department: string;
  status: string;
  worker_name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  eta_minutes?: number | null;
}

export interface WardMap {
  complaints: WardMapComplaint[];
  work_orders: WardMapWorkOrder[];
}

export interface WardSummary {
  summary: string;
  highlights: string[];
  recommended_actions: string[];
  generated_by: string;
  generated_at: string;
  complaint_count: number;
}

export interface ThreadMessage {
  id: string;
  complaint_id: string;
  author_id: string;
  author_name?: string | null;
  role: string;
  body: string;
  created_at: string;
}

export interface Conversation {
  complaint_id: string;
  complaint_title: string;
  messages: ThreadMessage[];
}

export interface EscalationResult {
  complaint_id: string;
  status: string;
  note: string;
}

export interface WardWorkOrder {
  id: string;
  complaint_id: string;
  incident?: string | null;
  department: string;
  priority?: string | null;
  status: string;
  worker_name?: string | null;
  eta_minutes?: number | null;
  due_at?: string | null;
}

export interface ClusterItem {
  id: string;
  complaint_id: string;
  title: string;
  status: string;
  priority?: string | null;
  created_at: string;
  similarity?: number | null;
  distance_m?: number | null;
  correlation_status?: string | null;
}

export interface Cluster {
  base_complaint_id: string;
  base_title: string;
  status: string;
  members: ClusterItem[];
}

// --------------------------------------------------------------------------- //
// API functions
// --------------------------------------------------------------------------- //

export async function fetchWardDashboard(): Promise<WardDashboard> {
  return authorizedJson<WardDashboard>("/api/v1/ward-rep/dashboard");
}

export async function fetchWardMap(): Promise<WardMap> {
  return authorizedJson<WardMap>("/api/v1/ward-rep/map");
}

export async function fetchWardSummary(): Promise<WardSummary> {
  return authorizedJson<WardSummary>("/api/v1/ward-rep/summary");
}

export async function fetchConversation(
  complaintId: string
): Promise<Conversation> {
  return authorizedJson<Conversation>(
    `/api/v1/ward-rep/complaints/${complaintId}/conversation`
  );
}

export async function sendUpdate(
  complaintId: string,
  body: string
): Promise<Conversation> {
  return authorizedJson<Conversation>(
    `/api/v1/ward-rep/complaints/${complaintId}/send-update`,
    { method: "POST", body: JSON.stringify({ body }) }
  );
}

export async function requestEscalation(
  complaintId: string,
  reason: string
): Promise<EscalationResult> {
  return authorizedJson<EscalationResult>(
    `/api/v1/ward-rep/complaints/${complaintId}/escalate`,
    { method: "POST", body: JSON.stringify({ body: reason }) }
  );
}

export async function fetchWorkOrder(
  complaintId: string
): Promise<WardWorkOrder | null> {
  return authorizedJson<WardWorkOrder | null>(
    `/api/v1/ward-rep/complaints/${complaintId}/work-order`
  );
}

export async function fetchCluster(complaintId: string): Promise<Cluster> {
  return authorizedJson<Cluster>(
    `/api/v1/ward-rep/complaints/${complaintId}/cluster`
  );
}
