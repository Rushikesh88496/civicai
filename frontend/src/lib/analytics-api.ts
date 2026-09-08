"use client";

import { ApiError, getAccessToken } from "@/lib/auth-api";
import { CATEGORY_LABELS } from "@/components/dashboard/format";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --------------------------------------------------------------------------- //
// Types (mirror the backend /analytics and /rating schemas)
// --------------------------------------------------------------------------- //

export interface AnalyticsFilters {
  date_from?: string;
  date_to?: string;
  ward_id?: string;
  department?: string;
  category?: string;
  priority?: string;
}

export interface AppliedAnalyticsFilters {
  date_from: string | null;
  date_to: string | null;
  ward_id: string | null;
  department: string | null;
  category: string | null;
  priority: string | null;
}

export interface SatisfactionBucket {
  rating: number;
  count: number;
}

export interface AnalyticsKpis {
  total_complaints: number;
  resolved: number;
  resolution_rate: number;
  response_seconds_avg: number | null;
  response_seconds_median: number | null;
  response_count: number;
  resolution_seconds_avg: number | null;
  resolution_seconds_median: number | null;
  resolution_count: number;
  sla_compliance_rate: number | null;
  sla_within: number;
  sla_overdue: number;
  sla_orders_with_deadline: number;
  ai_triaged: number;
  ai_triage_rate: number;
  escalated: number;
  escalation_rate: number;
  satisfaction_avg: number | null;
  satisfaction_count: number;
  satisfaction_distribution: SatisfactionBucket[];
}

export interface TimePoint {
  period: string;
  total: number;
  resolved: number;
}

export interface CategoryPoint {
  category: string;
  total: number;
  resolved: number;
  rate: number;
}

export interface WardPoint {
  ward_id: string | null;
  ward_name: string;
  total: number;
  resolved: number;
}

export interface DepartmentPoint {
  department: string;
  total: number;
  completed: number;
  avg_completion_seconds: number | null;
  sla_within: number;
  sla_overdue: number;
  compliance_rate: number | null;
  escalated: number;
}

export interface SlaPoint {
  priority: string;
  total: number;
  within: number;
  overdue: number;
}

export interface AnalyticsCharts {
  complaints_over_time: TimePoint[];
  resolution_trend: TimePoint[];
  categories: CategoryPoint[];
  wards: WardPoint[];
  departments: DepartmentPoint[];
  sla_performance: SlaPoint[];
}

export interface AnalyticsOverview {
  applied_filters: AppliedAnalyticsFilters;
  kpis: AnalyticsKpis;
  charts: AnalyticsCharts;
}

export interface HeatmapCluster {
  latitude: number;
  longitude: number;
  count: number;
  weight: number;
}

export interface HeatmapOut {
  total_points: number;
  clusters: HeatmapCluster[];
}

// --------------------------------------------------------------------------- //
// Filter option lists for the analytics filter bar
// --------------------------------------------------------------------------- //

export const ANALYTICS_CATEGORIES: Array<{ value: string; label: string }> =
  Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label }));

export const ANALYTICS_DEPARTMENTS: Array<{ value: string; label: string }> = [
  { value: "WATER", label: "Water" },
  { value: "ROADS", label: "Roads" },
  { value: "ELECTRICAL", label: "Electrical" },
  { value: "WASTE", label: "Waste" },
  { value: "DRAINAGE", label: "Drainage" },
  { value: "PARKS", label: "Parks" },
  { value: "EMERGENCY_DISASTER", label: "Emergency / Disaster" },
];

export const ANALYTICS_PRIORITIES: Array<{ value: string; label: string }> = [
  { value: "P1_CRITICAL", label: "P1 Critical" },
  { value: "P2_HIGH", label: "P2 High" },
  { value: "P3_MEDIUM", label: "P3 Medium" },
  { value: "P4_LOW", label: "P4 Low" },
];

// --------------------------------------------------------------------------- //
// API calls
// --------------------------------------------------------------------------- //

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // ignore parse errors
  }
  return res.statusText || "Request failed.";
}

function toQuery(filters: AnalyticsFilters): string {
  const params = new URLSearchParams();
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.ward_id) params.set("ward_id", filters.ward_id);
  if (filters.department) params.set("department", filters.department);
  if (filters.category) params.set("category", filters.category);
  if (filters.priority) params.set("priority", filters.priority);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function fetchAnalyticsOverview(
  filters: AnalyticsFilters
): Promise<AnalyticsOverview> {
  return authorizedGet<AnalyticsOverview>(
    `/api/v1/analytics/overview${toQuery(filters)}`
  );
}

export async function fetchAnalyticsHeatmap(
  filters: AnalyticsFilters
): Promise<HeatmapOut> {
  return authorizedGet<HeatmapOut>(`/api/v1/analytics/heatmap${toQuery(filters)}`);
}

export async function downloadAnalyticsCsv(filters: AnalyticsFilters): Promise<void> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const res = await fetch(`${API_BASE_URL}/api/v1/analytics/export${toQuery(filters)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match ? match[1] : `analytics_complaints_${Date.now()}.csv`;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function authorizedGet<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return res.json() as Promise<T>;
}