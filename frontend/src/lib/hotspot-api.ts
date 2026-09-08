"use client";

import { ApiError, getAccessToken } from "@/lib/auth-api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface HotspotModelInfo {
  version: number;
  kind: string;
  status: string;
  is_active: boolean;
  trained_at: string;
  artifact_filename: string;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
}

export type RiskTier = "high" | "medium" | "low";

export interface HotspotRiskCell {
  cell_id: string;
  latitude: number;
  longitude: number;
  risk_score: number;
  expected_volume: number;
  tier: RiskTier;
  ward_code?: string | null;
  ward_name?: string | null;
  trailing7: number;
}

export interface HotspotPredictions {
  ai_prediction: boolean;
  disclaimer: string;
  horizon_days: number;
  inference_at: string;
  model: HotspotModelInfo;
  cells: HotspotRiskCell[];
  population_cells: number;
  complaint_events_used: number;
  complaints_outside_grid: number;
}

export interface HotspotTrainingOut {
  trained: boolean;
  version: number;
  model: HotspotModelInfo;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
  rows: number;
  duration_seconds: number;
}

export interface HotspotStatus {
  trained: boolean;
  model?: HotspotModelInfo | null;
  message: string;
}

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // ignore parse errors
  }
  return res.statusText || "Request failed.";
}

async function hotspotFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return res.json() as Promise<T>;
}

export async function fetchHotspotStatus(): Promise<HotspotStatus> {
  return hotspotFetch<HotspotStatus>("/api/v1/hotspots/status");
}

export async function fetchHotspotPredictions(): Promise<HotspotPredictions> {
  return hotspotFetch<HotspotPredictions>("/api/v1/hotspots/predictions");
}

export async function trainHotspotModel(): Promise<HotspotTrainingOut> {
  return hotspotFetch<HotspotTrainingOut>("/api/v1/hotspots/train", { method: "POST" });
}

export function riskTierColor(tier: RiskTier): string {
  switch (tier) {
    case "high":
      return "#dc2626";
    case "medium":
      return "#f59e0b";
    default:
      return "#059669";
  }
}

/** Dig a numeric leaf out of the nested model.metrics object, or null. */
export function modelMetric(model: HotspotModelInfo, path: string[]): number | null {
  let current: unknown = model.metrics;
  for (const key of path) {
    if (!current || typeof current !== "object") return null;
    const next = (current as Record<string, unknown>)[key];
    if (next === undefined || next === null) return null;
    current = next;
  }
  return typeof current === "number" && Number.isFinite(current) ? current : null;
}