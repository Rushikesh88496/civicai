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
  // Provenance for assets synced from the verified facility registry (Part 37).
  source?: string | null;
  source_dataset?: string | null;
  source_url?: string | null;
  source_id?: string | null;
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
  history_records: number;
  minimum_history: number;
}

export interface InfrastructureStatus {
  trained: boolean;
  prediction_status: string;
  model?: InfrastructureModelInfo | null;
  message: string;
  registered_assets: number;
  minimum_assets: number;
  history_records: number;
  minimum_history: number;
}

export interface InfrastructureTrainingOut {
  trained: boolean;
  status: string;
  version?: number | null;
  model: InfrastructureModelInfo | null;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
  rows: number;
  duration_seconds: number;
  message: string;
  registered_assets: number;
  minimum_assets: number;
  history_records: number;
  minimum_history: number;
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

export async function fetchInfrastructureAssets(): Promise<InfrastructureAsset[]> {
  return infraFetch<InfrastructureAsset[]>("/api/v1/infrastructure/assets");
}

// --------------------------------------------------------------------------- //
// Real asset registry sync (Part 37) — predictive assets from the verified
// facility registry, provenance-keyed and idempotent.
// --------------------------------------------------------------------------- //

export interface AssetRegistryCategoryCountsOut {
  category: string;
  asset_category?: string | null;
  available: number;
  registered: number;
  updated: number;
  skipped_duplicate: number;
}

export interface AssetRegistrySyncOut {
  source: string;
  source_dataset?: string | null;
  inserted: number;
  updated: number;
  skipped_duplicate: number;
  unlocated: number;
  registered_total: number;
  by_category: AssetRegistryCategoryCountsOut[];
  message: string;
}

export async function syncInfrastructureAssets(): Promise<AssetRegistrySyncOut> {
  return infraFetch<AssetRegistrySyncOut>("/api/v1/infrastructure/assets/sync", {
    method: "POST",
  });
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

// --------------------------------------------------------------------------- //
// Real Nearby Infrastructure Data System (verified facility registry)
// --------------------------------------------------------------------------- //

export type RegisteredCategory =
  | "HOSPITAL"
  | "SCHOOL"
  | "BUS_STOP"
  | "POLICE_STATION"
  | "FIRE_STATION"
  | "TRANSPORT"
  | "PUBLIC_FACILITY"
  | "GOVERNMENT_BUILDING"
  | "ROAD"
  | "OTHER";

export type RegistryStatus =
  | "FOUND"
  | "NO_VERIFIED_RECORDS"
  | "PENDING_VERIFICATION"
  | "DATA_UNAVAILABLE";

export interface NearbyPlaceOut {
  id?: string | null;
  name: string;
  category: RegisteredCategory;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  distance_m?: number | null;
  verification_status: RegistryStatus;
  source?: string | null;
  source_dataset?: string | null;
  kind?: string | null;
  is_demo: boolean;
}

export interface NearbyCategorySummaryOut {
  category: RegisteredCategory;
  status: RegistryStatus;
  count: number;
  places: NearbyPlaceOut[];
  note: string;
}

export interface NearbyInfrastructureOut {
  latitude: number;
  longitude: number;
  radius_m: number;
  categories: NearbyCategorySummaryOut[];
  search_status: "resolved" | "partial" | "degraded";
  registry_total: number;
  registry_categories: Record<string, number>;
  live_fallback_used: boolean;
  query_id?: string | null;
  cached: boolean;
  resolved_at: string;
}

export interface NearbyInfrastructureIn {
  latitude: number;
  longitude: number;
  radius_m?: number | null;
  categories?: RegisteredCategory[] | null;
  limit?: number;
  use_cache?: boolean;
}

export interface RegistryAssetOut {
  id: string;
  name: string;
  category: RegisteredCategory;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  source?: string | null;
  source_dataset?: string | null;
  source_url?: string | null;
  source_id?: string | null;
  verification_status: RegistryStatus;
  last_verified_at?: string | null;
  ward_id?: string | null;
  ward_code?: string | null;
  ward_name?: string | null;
  is_demo: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RegistrySummaryOut {
  total: number;
  verified: number;
  pending: number;
  unlocated: number;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  last_verified_at?: string | null;
}

export interface RegistryListOut {
  items: RegistryAssetOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface RegistryCategoryCountsOut {
  category: string;
  fetched: number;
  inserted: number;
  updated: number;
  skipped_duplicate: number;
  skipped_unparseable: number;
  failed: number;
}

export interface RegistrySyncOut {
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  source: string;
  source_dataset?: string | null;
  source_url?: string | null;
  wards_covered: number;
  fetched_total: number;
  inserted: number;
  updated: number;
  skipped_duplicate: number;
  skipped_unparseable: number;
  failed_total: number;
  by_category: RegistryCategoryCountsOut[];
  message: string;
}

export async function fetchNearbyInfrastructure(
  payload: NearbyInfrastructureIn
): Promise<NearbyInfrastructureOut> {
  return infraFetch<NearbyInfrastructureOut>("/api/v1/infrastructure/nearby", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchRegistrySummary(): Promise<RegistrySummaryOut> {
  return infraFetch<RegistrySummaryOut>("/api/v1/infrastructure/registry/summary");
}

export async function fetchRegistry(
  params: {
    category?: RegisteredCategory;
    verificationStatus?: RegistryStatus;
    source?: string;
    limit?: number;
    offset?: number;
  } = {}
): Promise<RegistryListOut> {
  const query = new URLSearchParams();
  if (params.category) query.set("category", params.category);
  if (params.verificationStatus) query.set("verification_status", params.verificationStatus);
  if (params.source) query.set("source", params.source);
  query.set("limit", String(params.limit ?? 100));
  query.set("offset", String(params.offset ?? 0));
  return infraFetch<RegistryListOut>(`/api/v1/infrastructure/registry?${query.toString()}`);
}

export async function syncRegistry(force = false): Promise<RegistrySyncOut> {
  return infraFetch<RegistrySyncOut>("/api/v1/infrastructure/registry/sync", {
    method: "POST",
    body: JSON.stringify({ source: "openstreetmap", force }),
  });
}

export const registryStatusLabel: Record<RegistryStatus, string> = {
  FOUND: "Verified",
  NO_VERIFIED_RECORDS: "No verified records",
  PENDING_VERIFICATION: "Pending verification",
  DATA_UNAVAILABLE: "Data unavailable",
};