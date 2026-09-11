"use client";

import { authorizedFetch } from "@/lib/auth-api";

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

export interface ModelReadiness {
  prediction_status: string;
  message: string;
  records_available: number;
  observations_available: number;
  minimum_records: number;
  minimum_observations: number;
}

export interface HotspotPredictions extends ModelReadiness {
  ai_prediction: boolean;
  disclaimer: string;
  horizon_days: number;
  inference_at: string | null;
  model: HotspotModelInfo | null;
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

export interface HotspotStatus extends ModelReadiness {
  trained: boolean;
  model?: HotspotModelInfo | null;
}

export async function fetchHotspotStatus(): Promise<HotspotStatus> {
  return authorizedFetch<HotspotStatus>("/api/v1/hotspots/status");
}

export async function fetchHotspotPredictions(): Promise<HotspotPredictions> {
  return authorizedFetch<HotspotPredictions>("/api/v1/hotspots/predictions");
}

export async function trainHotspotModel(): Promise<HotspotTrainingOut> {
  return authorizedFetch<HotspotTrainingOut>("/api/v1/hotspots/train", { method: "POST" });
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