"use client";

import { authorizedFetch } from "@/lib/auth-api";

export type InfraRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type InfraReviewStatus = "PENDING" | "APPROVED" | "REJECTED";
export type PreventiveWorkOrderStatus =
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "COMPLETED"
  | "CANCELLED";

export interface InfrastructureModelInfo {
  version: number;
  kind: string;
  status: string;
  is_active: boolean;
  trained_at: string;
  artifact_filename: string;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
}

export interface InfrastructureAsset {
  id: string;
  name: string;
  category: string;
  ward_id?: string | null;
  ward_code?: string | null;
  ward_name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  address?: string | null;
  installed_at?: string | null;
  condition_note?: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AssetPrediction {
  id: string;
  asset: InfrastructureAsset;
  model_version: number;
  failure_probability: number;
  risk_level: InfraRiskLevel;
  recommended_inspection: string;
  supporting_factors: string[];
  history: Record<string, unknown>;
  ai_prediction: boolean;
  review_status: InfraReviewStatus;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  predicted_at: string;
}

export interface InfrastructurePredictions {
  ai_prediction: boolean;
  disclaimer: string;
  prediction_status: string;
  inference_at: string | null;
  model: InfrastructureModelInfo | null;
  assets: AssetPrediction[];
  assets_assessed: number;
  assets_skipped: number;
  horizon_days: number;
  message: string;
  registered_assets: number;
  minimum_assets: number;
}

export interface InfrastructureStatus {
  trained: boolean;
  prediction_status: string;
  model?: InfrastructureModelInfo | null;
  message: string;
  registered_assets: number;
  minimum_assets: number;
}

export interface InfrastructureTrainingOut {
  trained: boolean;
  version: number;
  model: InfrastructureModelInfo;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
  rows: number;
  duration_seconds: number;
}

export interface InfrastructureReviewOut {
  id: string;
  review_status: InfraReviewStatus;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
}

export interface PreventiveWorkOrderOut {
  id: string;
  prediction_id: string;
  asset: InfrastructureAsset;
  department: string;
  recommended_action: string;
  status: PreventiveWorkOrderStatus;
  due_at?: string | null;
  created_by?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  note?: string | null;
  created_at: string;
}

async function infraFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  return authorizedFetch<T>(path, init);
}

export async function fetchInfrastructureStatus(): Promise<InfrastructureStatus> {
  return infraFetch<InfrastructureStatus>("/api/v1/infrastructure/status");
}

export async function fetchInfrastructurePredictions(): Promise<InfrastructurePredictions> {
  return infraFetch<InfrastructurePredictions>("/api/v1/infrastructure/predictions");
}

export async function trainInfrastructureModel(): Promise<InfrastructureTrainingOut> {
  return infraFetch<InfrastructureTrainingOut>("/api/v1/infrastructure/train", {
    method: "POST",
  });
}

export async function reviewPrediction(
  predictionId: string,
  decision: "APPROVED" | "REJECTED",
  note?: string
): Promise<InfrastructureReviewOut> {
  return infraFetch<InfrastructureReviewOut>(
    `/api/v1/infrastructure/predictions/${predictionId}/review`,
    { method: "POST", body: JSON.stringify({ decision, note: note || null }) }
  );
}

export async function createPreventiveWorkOrder(
  predictionId: string,
  department: string,
  recommendedAction?: string
): Promise<PreventiveWorkOrderOut> {
  return infraFetch<PreventiveWorkOrderOut>(
    `/api/v1/infrastructure/predictions/${predictionId}/work-orders`,
    {
      method: "POST",
      body: JSON.stringify({ department, recommended_action: recommendedAction || null }),
    }
  );
}

export function riskLevelVariant(
  level: InfraRiskLevel
): "success" | "warning" | "destructive" | "default" | "secondary" {
  switch (level) {
    case "LOW":
      return "success";
    case "MEDIUM":
      return "warning";
    case "HIGH":
      return "destructive";
    case "CRITICAL":
      return "default";
    default:
      return "secondary";
  }
}

export function riskLevelColor(level: InfraRiskLevel): string {
  switch (level) {
    case "LOW":
      return "#059669";
    case "MEDIUM":
      return "#f59e0b";
    case "HIGH":
      return "#dc2626";
    case "CRITICAL":
      return "#7c3aed";
    default:
      return "#6b7280";
  }
}

export const INFRA_CATEGORIES = [
  "ROAD",
  "BRIDGE",
  "WATER_MAIN",
  "SEWER",
  "DRAINAGE",
  "STREET_LIGHTING",
  "PARK",
  "PUBLIC_BUILDING",
] as const;

/** Suggest the owning department for a preventive work order by asset category. */
export function departmentForCategory(category: string): string {
  switch (category) {
    case "ROAD":
    case "BRIDGE":
      return "ROADS";
    case "WATER_MAIN":
      return "WATER";
    case "SEWER":
    case "DRAINAGE":
      return "SANITATION";
    case "STREET_LIGHTING":
      return "ELECTRICITY";
    case "PARK":
    case "PUBLIC_BUILDING":
      return "PARKS";
    default:
      return "WORKS";
  }
}

/** Dig a numeric leaf out of the nested model.metrics object, or null. */
export function modelMetric(model: InfrastructureModelInfo, path: string[]): number | null {
  let current: unknown = model.metrics;
  for (const key of path) {
    if (!current || typeof current !== "object") return null;
    const next = (current as Record<string, unknown>)[key];
    if (next === undefined || next === null) return null;
    current = next;
  }
  return typeof current === "number" && Number.isFinite(current) ? current : null;
}