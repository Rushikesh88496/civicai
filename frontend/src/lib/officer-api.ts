"use client";

import { authorizedFetch } from "@/lib/auth-api";

async function authorizedGet<T>(path: string): Promise<T> {
  return authorizedFetch<T>(path);
}

async function authorizedRequest<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  return authorizedFetch<T>(path, init);
}

// --------------------------------------------------------------------------- //
// Types (mirror the backend /command-center schemas)
// --------------------------------------------------------------------------- //

export interface CommandCenterKpis {
  total_complaints: number;
  p1: number;
  p2: number;
  p3: number;
  p4: number;
  pending: number;
  in_progress: number;
  resolved: number;
  sla_breaches: number;
  sla_at_risk: number;
}

export interface CommandCenterComplaint {
  id: string;
  complaint_id: string;
  title: string;
  description?: string | null;
  incident?: string | null;
  category: string;
  status: string;
  priority?: string | null;
  priority_score?: number | null;
  complaint_priority?: string | null;
  department?: string | null;
  ward_code?: string | null;
  ward_name?: string | null;
  created_at: string;
  updated_at?: string | null;
  sla_due_at?: string | null;
  work_order_status?: string | null;
}

export interface CommandCenterQueue {
  items: CommandCenterComplaint[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface MapComplaint {
  id: string;
  title: string;
  status: string;
  priority?: string | null;
  department?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  ward_code?: string | null;
  created_at: string;
}

export interface MapWorkOrder {
  id: string;
  complaint_id: string;
  department: string;
  status: string;
  worker_name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  eta_minutes?: number | null;
}

export interface MapWard {
  ward_id: string;
  name: string;
  code: string;
  complaint_count: number;
}

export interface MapHotspot {
  ward_id?: string | null;
  ward_code?: string | null;
  ward_name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  complaint_count: number;
  open_count: number;
  priority_weight: number;
}

export interface CommandCenterMap {
  complaints: MapComplaint[];
  work_orders: MapWorkOrder[];
  wards: MapWard[];
  hotspots: MapHotspot[];
}

export interface AgentActivity {
  agent: string;
  status: string;
  count: number;
  last_run_at?: string | null;
}

export interface AgentSummary {
  agent: string;
  label: string;
  enabled: boolean;
  total: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
  last_activity_at?: string | null;
}

export interface AiActivity {
  last_updated: string;
  agents: AgentSummary[];
  breakdown: AgentActivity[];
}

export interface CommandCenterSnapshot {
  type: string;
  kpis: CommandCenterKpis;
  ai_activity?: AiActivity | null;
  changed_at: string;
}

export interface CommandCenterQueueParams {
  page?: number;
  page_size?: number;
  status?: string;
  category?: string;
  priority?: string;
  ward_id?: string;
  department?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
}

// --------------------------------------------------------------------------- //
// API functions
// --------------------------------------------------------------------------- //

export async function fetchCommandCenterKpis(): Promise<CommandCenterKpis> {
  return authorizedGet<CommandCenterKpis>("/api/v1/command-center/kpis");
}

export async function fetchCommandCenterQueue(
  params: CommandCenterQueueParams = {}
): Promise<CommandCenterQueue> {
  const qs = new URLSearchParams();
  (Object.keys(params) as (keyof CommandCenterQueueParams)[]).forEach((k) => {
    const v = params[k];
    if (v !== undefined && v !== null && v !== "") {
      qs.set(k, String(v));
    }
  });
  const q = qs.toString();
  return authorizedGet<CommandCenterQueue>(
    `/api/v1/command-center/queue${q ? `?${q}` : ""}`
  );
}

export async function fetchCommandCenterMap(): Promise<CommandCenterMap> {
  return authorizedGet<CommandCenterMap>("/api/v1/command-center/map");
}

export async function fetchCommandCenterAiActivity(): Promise<AiActivity> {
  return authorizedGet<AiActivity>("/api/v1/command-center/ai-activity");
}

export async function fetchCommandCenterSnapshot(): Promise<CommandCenterSnapshot> {
  return authorizedGet<CommandCenterSnapshot>("/api/v1/command-center/snapshot");
}

// --------------------------------------------------------------------------- //
// SLA Monitor (Part 20)
// --------------------------------------------------------------------------- //

export type SlaState = "ON_TRACK" | "AT_RISK" | "BREACHED" | "COMPLETED";

export interface SlaCounts {
  open: number;
  on_track: number;
  at_risk: number;
  breached: number;
  completed: number;
  no_deadline: number;
}

export interface OrderSlaSnapshot {
  work_order_id: string;
  complaint_id: string;
  incident?: string | null;
  category?: string | null;
  department: string;
  priority?: string | null;
  status: string;
  worker_name?: string | null;
  sla_hours?: number | null;
  due_at?: string | null;
  state: SlaState;
  progress: number;
  remaining_seconds?: number | null;
  remaining_human?: string | null;
  breached: boolean;
  at_risk: boolean;
  policy_id?: string | null;
}

export interface SlaOrdersPage {
  items: OrderSlaSnapshot[];
  counts: SlaCounts;
  total: number;
  page: number;
  page_size: number;
}

export interface SlaScanOutput {
  checked_at: string;
  counts: SlaCounts;
  orders: OrderSlaSnapshot[];
  notifications_sent: Record<string, number>;
}

export interface SlaRunOut {
  id: string;
  agent: string;
  status: string;
  duration_ms?: number | null;
  structured_result?: SlaScanOutput | null;
  error?: string | null;
  started_at: string;
  ended_at?: string | null;
}

export interface SlaRunResponse {
  run_id: string;
  status: string;
  result?: SlaScanOutput | null;
  error?: string | null;
  retry_allowed: boolean;
}

export interface SlaPolicy {
  id: string;
  name?: string | null;
  priority?: string | null;
  department?: string | null;
  category?: string | null;
  sla_hours: number;
  at_risk_percent: number;
  escalate_on_breach: boolean;
  active: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface SlaPolicyIn {
  name?: string | null;
  priority?: string | null;
  department?: string | null;
  category?: string | null;
  sla_hours: number;
  at_risk_percent: number;
  escalate_on_breach: boolean;
  active: boolean;
}

export interface SlaOrdersParams {
  page?: number;
  page_size?: number;
  state?: SlaState | "";
  department?: string;
  priority?: string;
  search?: string;
}

export async function fetchSlaOrders(params: SlaOrdersParams = {}): Promise<SlaOrdersPage> {
  const qs = new URLSearchParams();
  (Object.keys(params) as (keyof SlaOrdersParams)[]).forEach((k) => {
    const v = params[k];
    if (v !== undefined && v !== null && v !== "") {
      qs.set(k, String(v));
    }
  });
  const q = qs.toString();
  return authorizedGet<SlaOrdersPage>(
    `/api/v1/sla/orders${q ? `?${q}` : ""}`
  );
}

export async function runSlaMonitor(
  department?: string,
  priority?: string
): Promise<SlaRunResponse> {
  const qs = new URLSearchParams();
  if (department) qs.set("department", department);
  if (priority) qs.set("priority", priority);
  const q = qs.toString();
  return authorizedRequest<SlaRunResponse>(
    `/api/v1/sla/run${q ? `?${q}` : ""}`,
    { method: "POST" }
  );
}

export async function fetchSlaRun(): Promise<SlaRunOut | null> {
  return authorizedGet<SlaRunOut | null>("/api/v1/sla/run");
}

export async function fetchSlaPolicies(): Promise<SlaPolicy[]> {
  return authorizedGet<SlaPolicy[]>("/api/v1/sla/policies");
}

export async function createSlaPolicy(payload: SlaPolicyIn): Promise<SlaPolicy> {
  return authorizedRequest<SlaPolicy>("/api/v1/sla/policies", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateSlaPolicy(
  id: string,
  payload: SlaPolicyIn
): Promise<SlaPolicy> {
  return authorizedRequest<SlaPolicy>(`/api/v1/sla/policies/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteSlaPolicy(id: string): Promise<void> {
  return authorizedRequest<void>(`/api/v1/sla/policies/${id}`, {
    method: "DELETE",
  });
}

// --------------------------------------------------------------------------- //
// Realtime - websocket command-center channel
// --------------------------------------------------------------------------- //

export function commandCenterWsUrl(): string {
  // Token is appended later by the caller (getAccessToken is async) and the
  // ws scheme depends on whether the frontend talks to localhost over http.
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const host = base.replace(/^https?:\/\//, "");
  const scheme = base.startsWith("https") ? "wss" : "ws";
  return `${scheme}://${host}/ws/command-center`;
}
