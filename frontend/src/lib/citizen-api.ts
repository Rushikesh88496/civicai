"use client";

// Client-side helpers for the citizen dashboard data. Reuses the access-token
// machinery from auth-api (in-memory access token + transparent refresh) so the
// dashboard is only ever populated with the authenticated user's own data.

import { authorizedFetch } from "@/lib/auth-api";

export type ComplaintStatus =
  | "OPEN"
  | "IN_PROGRESS"
  | "RESOLVED"
  | "ESCALATED"
  | "SUBMITTED"
  | "AI_ANALYZING"
  | "EVIDENCE_VERIFIED"
  | "WARD_IDENTIFIED"
  | "PRIORITIZED"
  | "DEPARTMENT_ASSIGNED"
  | "WORK_ORDER_CREATED"
  | "WORKER_ASSIGNED"
  | "CITIZEN_VERIFIED"
  | "CLOSED";
export type ComplaintPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Complaint {
  id: string;
  category: string;
  title: string;
  description: string | null;
  location: string | null;
  priority: ComplaintPriority;
  status: ComplaintStatus;
  created_at: string;
  updated_at: string;
}

export interface ComplaintMedia {
  id: string;
  media_type: "IMAGE" | "VIDEO";
  original_filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
  created_at: string;
}

export interface ComplaintLocation {
  latitude: number;
  longitude: number;
  address: string | null;
  source: string;
  geopoint_denied: boolean;
  // Device-reported GPS horizontal accuracy in metres (Part 31/33).
  accuracy_m: number | null;
}

export interface WardInfo {
  code: string | null;
  name: string | null;
  description: string | null;
  representative: WardRepresentative | null;
}

export interface WardShort {
  id: string | null;
  name: string | null;
  code: string | null;
}

export interface ComplaintDetail extends Complaint {
  user_id: string;
  ward: WardShort | null;
  department: string | null;
  complaint_location: ComplaintLocation | null;
  media: ComplaintMedia[];
}

export interface TimelineEvent {
  id: string;
  status: ComplaintStatus;
  actor_id: string | null;
  note: string | null;
  recorded_at: string;
}

export interface ComplaintTimeline {
  complaint_id: string;
  current_status: ComplaintStatus;
  events: TimelineEvent[];
  // Part 32: work-order milestones merged into the complaint timeline so the
  // UI can render the full lifecycle (officer review → official assignment →
  // worker accepted → in progress → verification → resolved → closed).
  work_order_events: WorkOrderTimelineEvent[];
}

export interface WorkOrderTimelineEvent {
  work_order_id: string;
  action: string;
  status: string;
  actor_name: string | null;
  note: string | null;
  recorded_at: string;
}

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Urgency = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AgentRunStatus = "RUNNING" | "SUCCEEDED" | "FAILED";

export interface TriageResult {
  category: string;
  severity: Severity;
  urgency: Urgency;
  infrastructure_type: string;
  summary: string;
  confidence: number;
  recommended_action: string;
  human_review_required: boolean;
}

export interface AiTriageRun {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: TriageResult | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface WardRepresentative {
  name: string;
  email: string;
  title: string | null;
  status: string | null;
}

export interface ComplaintSummary {
  total: number;
  open: number;
  in_progress: number;
  resolved: number;
  escalated: number;
}

export interface DashboardData {
  complaints: ComplaintSummary;
  recent_complaints: Complaint[];
  ward: WardInfo;
}

async function authorizedGet<T>(path: string): Promise<T> {
  return authorizedFetch<T>(path);
}

export async function fetchDashboard(): Promise<DashboardData> {
  return authorizedGet<DashboardData>("/api/v1/citizen/dashboard");
}

export async function fetchMyWardRepresentative(): Promise<WardInfo> {
  return authorizedGet<WardInfo>("/api/v1/citizen/my-ward-representative");
}

export async function fetchComplaintDetail(id: string): Promise<ComplaintDetail> {
  return authorizedGet<ComplaintDetail>(`/api/v1/complaints/${id}`);
}

export async function fetchComplaintTimeline(id: string): Promise<ComplaintTimeline> {
  return authorizedGet<ComplaintTimeline>(`/api/v1/complaints/${id}/timeline`);
}

async function authorizedSend<T>(
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  return authorizedFetch<T>(path, {
    method: options.method ?? "GET",
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
  });
}

export async function fetchAiTriage(
  id: string
): Promise<AiTriageRun | null> {
  return authorizedSend<AiTriageRun | null>(`/api/v1/complaints/${id}/ai-triage`);
}

export interface RunTriageResponse {
  run_id: string;
  status: AgentRunStatus;
  result: TriageResult | null;
  error: string | null;
  retry_allowed: boolean;
}

export async function runAiTriage(
  id: string,
  language = "en"
): Promise<RunTriageResponse> {
  return authorizedSend<RunTriageResponse>(
    `/api/v1/complaints/${id}/triage`,
    { method: "POST", body: { language } }
  );
}

export interface VisionResult {
  visual_evidence_detected: boolean;
  detected_issue: string | null;
  severity: Severity | null;
  confidence: number | null;
  evidence_description: string | null;
  mismatch_detected: boolean;
  human_review_required: boolean;
}

export interface AiVisionRun {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: VisionResult | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export async function fetchAiVision(id: string): Promise<AiVisionRun | null> {
  return authorizedSend<AiVisionRun | null>(
    `/api/v1/complaints/${id}/vision-result`
  );
}

export interface RunVisionResponse {
  run_id: string;
  status: AgentRunStatus;
  result: VisionResult | null;
  error: string | null;
  retry_allowed: boolean;
}

export async function runAiVision(id: string): Promise<RunVisionResponse> {
  return authorizedSend<RunVisionResponse>(
    `/api/v1/complaints/${id}/vision`,
    { method: "POST" }
  );
}

export type CorrelationStatus =
  | "NEW_INCIDENT"
  | "POSSIBLE_DUPLICATE"
  | "CONFIRMED_DUPLICATE";
export type CorrelationMatchStatus =
  | "PENDING"
  | "CONFIRMED"
  | "REJECTED";

export interface CorrelationMatch {
  correlation_id: string | null;
  complaint_id: string;
  title: string;
  category: string | null;
  similarity: number;
  distance_m: number | null;
  time_diff_hours: number | null;
  category_match: boolean;
  score: number;
  reason: string;
  status: CorrelationMatchStatus;
}

export interface CorrelationResult {
  status: CorrelationStatus;
  best_match: CorrelationMatch | null;
  candidates_found: number;
  human_review_required: boolean;
  summary: string;
}

export interface AiCorrelationRun {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: CorrelationResult | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export async function fetchAiCorrelation(
  id: string
): Promise<AiCorrelationRun | null> {
  return authorizedSend<AiCorrelationRun | null>(
    `/api/v1/complaints/${id}/correlation-result`
  );
}

export interface RunCorrelationResponse {
  run_id: string;
  status: AgentRunStatus;
  result: CorrelationResult | null;
  error: string | null;
  retry_allowed: boolean;
}

export async function runAiCorrelation(id: string): Promise<RunCorrelationResponse> {
  return authorizedSend<RunCorrelationResponse>(
    `/api/v1/complaints/${id}/correlate`,
    { method: "POST", body: {} }
  );
}

export async function fetchCorrelations(id: string): Promise<CorrelationMatch[]> {
  return authorizedSend<CorrelationMatch[]>(
    `/api/v1/complaints/${id}/correlations`
  );
}

export async function confirmCorrelation(correlationId: string): Promise<CorrelationMatch> {
  return authorizedSend<CorrelationMatch>(
    `/api/v1/complaints/correlations/${correlationId}/confirm`,
    { method: "POST" }
  );
}

export async function rejectCorrelation(correlationId: string): Promise<CorrelationMatch> {
  return authorizedSend<CorrelationMatch>(
    `/api/v1/complaints/correlations/${correlationId}/reject`,
    { method: "POST" }
  );
}

// --------------------------------------------------------------------------- //
// GIS / Ward Detection & Spatial Intelligence (Part 10)
// --------------------------------------------------------------------------- //

export type CriticalLocationCategory =
  | "HOSPITAL"
  | "SCHOOL"
  | "BUS_STOP"
  | "POLICE_STATION"
  | "FIRE_STATION"
  | "ROAD"
  | "TRANSPORT"
  | "PUBLIC_FACILITY"
  | "GOVERNMENT_BUILDING"
  | "OTHER";

export type NearbyStatus = "available" | "empty" | "unavailable";

export interface GeoPlace {
  id: string | null;
  name: string;
  category: CriticalLocationCategory;
  address: string | null;
  latitude: number;
  longitude: number;
  distance_m: number | null;
  is_demo: boolean;
}

export interface WardDetected {
  ward_id: string;
  name: string;
  code: string | null;
  description: string | null;
  city: string;
  state: string;
  country: string;
  is_demo: boolean;
}

export interface ReverseGeocodeResult {
  address: string | null;
  display_name: string | null;
  source: string;
  degraded: boolean;
}

export interface GeoLookup {
  latitude: number;
  longitude: number;
  address: ReverseGeocodeResult | null;
  ward: WardDetected | null;
  nearby_roads: GeoPlace[];
  hospitals: GeoPlace[];
  schools: GeoPlace[];
  bus_stops: GeoPlace[];
  police_stations: GeoPlace[];
  fire_stations: GeoPlace[];
  public_facilities: GeoPlace[];
  government_buildings: GeoPlace[];
  critical_infrastructure: GeoPlace[];
  nearby_status: NearbyStatus;
  radius_m: number;
  demo_label: string;
  calculated_at: string;
}

export interface WardBoundary {
  ward_id: string;
  name: string;
  code: string | null;
  description: string | null;
  city: string;
  state: string;
  country: string;
  is_demo: boolean;
  geometry: number[][] | null;
  centroid: number[] | null;
}

export interface WardList {
  wards: WardBoundary[];
}

export async function runGeoLookup(
  latitude: number,
  longitude: number,
  radius_m?: number
): Promise<GeoLookup> {
  return authorizedSend<GeoLookup>(`/api/v1/geo/lookup`, {
    method: "POST",
    body: { latitude, longitude, ...(radius_m != null ? { radius_m } : {}) },
  });
}

export async function fetchGeoWards(): Promise<WardList> {
  return authorizedGet<WardList>("/api/v1/geo/wards");
}

export interface GeoDistance {
  distance_km: number;
  distance_m: number;
}

export async function runGeoDistance(
  latitudeA: number,
  longitudeA: number,
  latitudeB: number,
  longitudeB: number
): Promise<GeoDistance> {
  return authorizedSend<GeoDistance>(`/api/v1/geo/distance`, {
    method: "POST",
    body: {
      latitude_a: latitudeA,
      longitude_a: longitudeA,
      latitude_b: latitudeB,
      longitude_b: longitudeB,
    },
  });
}

// --------------------------------------------------------------------------- //
// Context Enrichment Agent (Part 11)
// --------------------------------------------------------------------------- //

export interface WeatherForecastDay {
  date: string;
  temperature_max: number | null;
  temperature_min: number | null;
  precipitation_sum: number | null;
}

export interface WeatherContext {
  temperature_c: number | null;
  precipitation_mm: number | null;
  rain_mm: number | null;
  wind_speed_kmh: number | null;
  weather_code: number | null;
  condition: string | null;
  cached: boolean;
  retrieved_at: string | null;
  available: boolean;
  forecast: WeatherForecastDay[];
}

export interface GisContext {
  latitude: number | null;
  longitude: number | null;
  address: string | null;
  address_source: string;
  address_degraded: boolean;
  ward_id: string | null;
  ward_name: string | null;
  ward_code: string | null;
  ward_description: string | null;
  ward_is_demo: boolean;
  radius_m: number | null;
  demo_label: string;
  available: boolean;
}

export interface HistoricalContext {
  total_prior: number;
  same_ward_count: number | null;
  window_hours: number | null;
  radius_m: number | null;
  ward_resolved: boolean;
  summary: string;
}

export interface InfrastructureEntry {
  name: string;
  category: string;
  distance_m: number | null;
}

export interface InfrastructureContext {
  radius_m: number | null;
  total_nearby: number;
  hospitals: number;
  schools: number;
  bus_stops: number;
  police_stations: number;
  fire_stations: number;
  public_facilities: number;
  government_buildings: number;
  major_roads: number;
  status: NearbyStatus;
  highlights: InfrastructureEntry[];
  places: InfrastructureEntry[];
  available: boolean;
}

export interface ContextSource {
  name: string;
  source_type: string;
  retrieved_at: string;
  params: Record<string, unknown>;
}

export interface ContextResult {
  weather_context: WeatherContext;
  gis_context: GisContext;
  historical_context: HistoricalContext;
  infrastructure_context: InfrastructureContext;
  sources: ContextSource[];
  summary: string;
}

export interface AiContextRun {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: ContextResult | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface RunContextResponse {
  run_id: string;
  status: AgentRunStatus;
  result: ContextResult | null;
  error: string | null;
  retry_allowed: boolean;
}

export async function fetchAiContext(id: string): Promise<AiContextRun | null> {
  return authorizedSend<AiContextRun | null>(
    `/api/v1/complaints/${id}/context-result`
  );
}

export async function runAiContext(id: string): Promise<RunContextResponse> {
  return authorizedSend<RunContextResponse>(
    `/api/v1/complaints/${id}/context`,
    { method: "POST", body: {} }
  );
}

export type DynamicPriority =
  | "P1_CRITICAL"
  | "P2_HIGH"
  | "P3_MEDIUM"
  | "P4_LOW";

export interface PrioritySignalInputs {
  severity: string;
  population: number;
  hospitals: number;
  schools: number;
  bus_stops: number;
  location_available: boolean;
  weather_condition: string | null;
  rain_mm: number | null;
  weather_available: boolean;
  complaint_count: number;
  historical_recurrence: number;
  ward_resolved: boolean;
  time_unresolved_hours: number;
}

export interface PriorityFactor {
  factor: string;
  input_value: string;
  present: boolean;
  weight: number;
  unit: number;
  contribution: number;
  description: string;
}

export type PriorityReadiness = "READY" | "PARTIAL" | "INSUFFICIENT_DATA";

export interface PriorityComponent {
  key: string;
  label: string;
  score: number | null;
  max_score: number;
  unit: number;
  status: string;
  input_value: string;
  explanation: string;
  source: string;
  calculated_at: string | null;
  details?: Record<string, unknown> | null;
}

export interface RiskAmplifier {
  key: string;
  label: string;
  points: number;
  applied: boolean;
  trigger_conditions: string[];
  evidence: string[];
  explanation: string;
}

export interface ComplaintSlaStatus {
  state: "ON_TRACK" | "AT_RISK" | "BREACHED" | "NO_POLICY";
  sla_hours: number | null;
  due_at: string | null;
  remaining_seconds: number | null;
  remaining_human: string | null;
  at_risk_percent: number | null;
  breached: boolean;
  escalation_level: number;
  policy_id: string | null;
  policy_name: string | null;
}

export interface DataSource {
  name: string;
  source_type: string;
  retrieved_at: string | null;
  params: Record<string, unknown>;
}

export interface PriorityResult {
  score: number;
  priority: DynamicPriority;
  factors: PriorityFactor[];
  components: PriorityComponent[];
  sources: DataSource[];
  risk_amplifiers: RiskAmplifier[];
  sla: ComplaintSlaStatus | null;
  data_status: PriorityReadiness;
  calculated_at: string;
  reason: string;
  inputs: PrioritySignalInputs;
  previous_score: number | null;
  previous_priority: DynamicPriority | null;
  changed: boolean;
  summary: string;
}

export interface AiPriorityRun {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: PriorityResult | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface RunPriorityResponse {
  run_id: string;
  status: AgentRunStatus;
  result: PriorityResult | null;
  error: string | null;
  retry_allowed: boolean;
}

export interface PriorityHistoryEntry {
  id: string;
  complaint_id: string;
  score: number;
  priority: DynamicPriority;
  previous_score: number | null;
  changed: boolean;
  calculated_at: string;
  summary: string | null;
}

export interface PriorityHistoryOut {
  complaint_id: string;
  entries: PriorityHistoryEntry[];
}

export async function fetchPriorityResult(
  id: string
): Promise<AiPriorityRun | null> {
  return authorizedSend<AiPriorityRun | null>(
    `/api/v1/complaints/${id}/priority-result`
  );
}

export async function runPriorityEngine(
  id: string
): Promise<RunPriorityResponse> {
  return authorizedSend<RunPriorityResponse>(
    `/api/v1/complaints/${id}/priority`,
    { method: "POST", body: {} }
  );
}

export async function fetchPriorityHistory(
  id: string
): Promise<PriorityHistoryOut> {
  return authorizedSend<PriorityHistoryOut>(
    `/api/v1/complaints/${id}/priority-history`
  );
}

// --------------------------------------------------------------------------- //
// Department routing (Part 13)
// --------------------------------------------------------------------------- //
export type RoutingDepartmentCode =
  | "WATER"
  | "ROADS"
  | "ELECTRICAL"
  | "WASTE"
  | "DRAINAGE"
  | "PARKS"
  | "EMERGENCY_DISASTER";

export interface RoutingSignalInputs {
  category: string;
  description: string | null;
  priority_bucket: string | null;
  priority_score: number | null;
  triage_severity: string | null;
  vision_summary: string | null;
  context_summary: string | null;
}

export interface RoutingInputs {
  category: string;
  description: string | null;
}

export interface RoutingResult {
  primary_department: RoutingDepartmentCode;
  secondary_departments: RoutingDepartmentCode[];
  routing_reason: string;
  confidence: number;
  ambiguous: boolean;
  changed: boolean;
  previous_department: RoutingDepartmentCode | null;
  inputs: RoutingSignalInputs;
}

export interface AiRoutingRun {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: RoutingResult | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface RunRoutingResponse {
  run_id: string;
  status: AgentRunStatus;
  result: RoutingResult | null;
  error: string | null;
  retry_allowed: boolean;
}

export interface RoutingHistoryEntry {
  id: string;
  complaint_id: string;
  primary_department: RoutingDepartmentCode;
  secondary_departments: RoutingDepartmentCode[];
  confidence: number;
  ambiguous: boolean;
  changed: boolean;
  previous_department: RoutingDepartmentCode | null;
  routing_reason: string | null;
  created_at: string;
}

export interface RoutingHistoryOut {
  complaint_id: string;
  entries: RoutingHistoryEntry[];
}

export interface DepartmentOverrideEntry {
  id: string;
  complaint_id: string;
  old_department: RoutingDepartmentCode | null;
  new_department: RoutingDepartmentCode;
  reason: string | null;
  override_by_name: string | null;
  created_at: string;
}

export interface DepartmentOverrideResponse {
  override: DepartmentOverrideEntry;
  current_department: RoutingDepartmentCode;
}

export interface DepartmentOverrideHistoryOut {
  complaint_id: string;
  overrides: DepartmentOverrideEntry[];
}

export async function fetchRoutingResult(
  id: string
): Promise<AiRoutingRun | null> {
  return authorizedSend<AiRoutingRun | null>(
    `/api/v1/complaints/${id}/routing-result`
  );
}

export async function runRouting(
  id: string
): Promise<RunRoutingResponse> {
  return authorizedSend<RunRoutingResponse>(
    `/api/v1/complaints/${id}/routing`,
    { method: "POST", body: {} }
  );
}

export async function fetchRoutingHistory(
  id: string
): Promise<RoutingHistoryOut> {
  return authorizedSend<RoutingHistoryOut>(
    `/api/v1/complaints/${id}/routing-history`
  );
}

export async function fetchOverrideHistory(
  id: string
): Promise<DepartmentOverrideHistoryOut> {
  return authorizedSend<DepartmentOverrideHistoryOut>(
    `/api/v1/complaints/${id}/routing/overrides`
  );
}

export async function submitOverride(
  id: string,
  payload: { new_department: RoutingDepartmentCode; reason: string }
): Promise<DepartmentOverrideResponse> {
  return authorizedSend<DepartmentOverrideResponse>(
    `/api/v1/complaints/${id}/routing/override`,
    { method: "POST", body: payload }
  );
}

// ---------------------------------------------------------------------------
// Part 14: Autonomous Dispatch & Work Orders
// ---------------------------------------------------------------------------

export type WorkOrderStatus =
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "WORK_COMPLETED"
  | "EVIDENCE_SUBMITTED"
  | "RETURNED_FOR_REWORK"
  | "COMPLETED"
  | "ESCALATED"
  | "REJECTED"
  | "CLOSED";

export type WorkOrderAction =
  | "APPROVE"
  | "ASSIGN"
  | "REASSIGN"
  | "ESCALATE"
  | "REJECT"
  | "CLOSE"
  | "DISPATCH"
  | "REWORK_REQUESTED"
  | "START_REWORK";

export interface DispatchCandidate {
  worker_id: string;
  name: string;
  score: number;
  available: boolean;
  availability: number;
  skill: number;
  distance: number;
  workload: number;
  equipment: number;
  department: number;
  ward: number;
  priority: number;
  distance_km: number | null;
  department_code: string | null;
  ward_code: string | null;
  active_orders: number;
  capacity: number | null;
  reasons: string[];
}

export interface DispatchRecommendation {
  department: string;
  priority: string | null;
  recommended_action: string;
  required_skills: string[];
  required_equipment: string[];
  recommended_worker_id: string | null;
  recommended_worker_name: string | null;
  // Concise deterministic explanation of the pick, built only from the actual
  // scored candidate data (skill / department / ward / availability / workload /
  // distance). Displayed to staff, never to citizens.
  recommended_worker_explanation: string | null;
  candidates: DispatchCandidate[];
  sla_hours: number | null;
  eta_minutes: number | null;
  eta_source: string | null;
  no_worker_reason: string | null;
}

export interface DispatchOutput {
  recommendation: DispatchRecommendation;
  inputs: {
    complaint_id: string;
    department: string;
    priority: string | null;
    required_skills: string[];
    required_equipment: string[];
    lat: number | null;
    lon: number | null;
    incident: string | null;
  };
}

export interface DispatchRunResponse {
  run_id: string;
  status: AgentRunStatus;
  work_order_id: string | null;
  result: DispatchOutput | null;
  error: string | null;
  retry_allowed: boolean;
}

export interface DispatchRunDetail {
  id: string;
  complaint_id: string | null;
  agent: string;
  model: string | null;
  status: AgentRunStatus;
  duration_ms: number | null;
  structured_result: DispatchOutput | null;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface WorkOrderDetail {
  id: string;
  complaint_id: string;
  incident: string | null;
  department: string;
  priority: string | null;
  location_lat: number | null;
  location_lon: number | null;
  address: string | null;
  sla_hours: number | null;
  due_at: string | null;
  recommended_action: string | null;
  status: WorkOrderStatus;
  eta_minutes: number | null;
  eta_source: string | null;
  worker_name: string | null;
  // Part 32: the worker the Dispatch Agent recommended, frozen at draft time.
  // Distinct from ``worker_name`` once an officer overrides the pick.
  recommended_worker_id: string | null;
  recommended_worker_name: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface WorkOrderListOut {
  complaint_id: string;
  work_orders: WorkOrderDetail[];
}

export interface WorkOrderStatusHistoryEntry {
  id: string;
  action: WorkOrderAction;
  from_status: WorkOrderStatus | null;
  to_status: WorkOrderStatus;
  actor_name: string | null;
  note: string | null;
  recorded_at: string;
}

export interface WorkOrderStatusHistoryOut {
  work_order_id: string;
  entries: WorkOrderStatusHistoryEntry[];
}

export interface WorkerAssignment {
  id: string;
  work_order_id: string;
  worker_id: string;
  worker_name: string | null;
  status: "ASSIGNED" | "REASSIGNED" | "UNASSIGNED";
  assigned_by_name: string | null;
  // Part 32 provenance: AI_RECOMMENDATION (officer accepted the pick),
  // OFFICER_OVERRIDE (different worker chosen), or MANUAL (no recommendation).
  origin: string | null;
  reason: string | null;
  assigned_at: string;
}

export interface WorkOrderDetailBundle {
  work_order: WorkOrderDetail;
  assignments: WorkerAssignment[];
  status_history: WorkOrderStatusHistoryEntry[];
}

export async function runDispatch(id: string): Promise<DispatchRunResponse> {
  return authorizedSend<DispatchRunResponse>(
    `/api/v1/complaints/${id}/dispatch`,
    { method: "POST", body: {} }
  );
}

export async function fetchDispatchResult(
  id: string
): Promise<DispatchRunDetail | null> {
  return authorizedSend<DispatchRunDetail | null>(
    `/api/v1/complaints/${id}/dispatch-result`
  );
}

export async function fetchComplaintWorkOrders(
  id: string
): Promise<WorkOrderListOut> {
  return authorizedSend<WorkOrderListOut>(
    `/api/v1/complaints/${id}/work-orders`
  );
}

export async function fetchWorkOrderDetail(
  id: string
): Promise<WorkOrderDetailBundle> {
  return authorizedSend<WorkOrderDetailBundle>(`/api/v1/work-orders/${id}`);
}

export async function fetchWorkOrderHistory(
  id: string
): Promise<WorkOrderStatusHistoryOut> {
  return authorizedSend<WorkOrderStatusHistoryOut>(
    `/api/v1/work-orders/${id}/history`
  );
}

export async function approveWorkOrder(
  id: string,
  note: string
): Promise<WorkOrderDetailBundle> {
  return authorizedSend<WorkOrderDetailBundle>(`/api/v1/work-orders/${id}/approve`, {
    method: "POST",
    body: { note },
  });
}

export async function assignWorkOrder(
  id: string,
  workerId: string,
  reason: string
): Promise<WorkOrderDetailBundle> {
  return authorizedSend<WorkOrderDetailBundle>(`/api/v1/work-orders/${id}/assign`, {
    method: "POST",
    body: { worker_id: workerId, reason },
  });
}

export async function reassignWorkOrder(
  id: string,
  workerId: string,
  reason: string
): Promise<WorkOrderDetailBundle> {
  return authorizedSend<WorkOrderDetailBundle>(`/api/v1/work-orders/${id}/reassign`, {
    method: "POST",
    body: { worker_id: workerId, reason },
  });
}

export async function escalateWorkOrder(
  id: string,
  reason: string
): Promise<WorkOrderDetailBundle> {
  return authorizedSend<WorkOrderDetailBundle>(`/api/v1/work-orders/${id}/escalate`, {
    method: "POST",
    body: { reason },
  });
}

export async function rejectWorkOrder(
  id: string,
  note: string
): Promise<WorkOrderDetailBundle> {
  return authorizedSend<WorkOrderDetailBundle>(`/api/v1/work-orders/${id}/reject`, {
    method: "POST",
    body: { note },
  });
}

// ---------------------------------------------------------------------------
// Part 19: AI Resolution Verification
// ---------------------------------------------------------------------------

export type VerificationStatus =
  | "VERIFIED"
  | "PARTIALLY_RESOLVED"
  | "NOT_RESOLVED"
  | "NEEDS_HUMAN_REVIEW";

export type VerificationReviewDecision =
  | "CONFIRM_VERIFIED"
  | "REQUIRES_FOLLOWUP"
  | "REQUEST_REWORK";

export interface WorkOrderVerification {
  id: string;
  work_order_id: string;
  complaint_id: string;
  before_photo_id: string | null;
  after_photo_id: string | null;
  before_url: string;
  after_url: string;
  repair_evidence: string | null;
  remaining_issue: string | null;
  confidence: number;
  verification_status: VerificationStatus;
  human_review_required: boolean;
  source: "groq" | "pixel-diff";
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
}

export type AiVerificationStatus =
  | "NOT_STARTED"
  | "PROCESSING"
  | "COMPLETED"
  | "PROVIDER_RATE_LIMITED"
  | "PROVIDER_UNAVAILABLE"
  | "INVALID_EVIDENCE"
  | "ANALYSIS_FAILED"
  | "MODEL_NOT_FOUND"
  | "MODEL_ACCESS_DENIED"
  | "CONFIGURATION";

export interface RunVerificationResponse {
  run_id: string;
  status: AgentRunStatus;
  result: WorkOrderVerification | null;
  error: string | null;
  retry_allowed: boolean;
  ai_status: AiVerificationStatus;
  message: string | null;
  retry_after_seconds: number | null;
}

export interface VerificationReviewOut {
  verification: WorkOrderVerification;
  work_order_status: WorkOrderStatus;
  reopened: boolean;
  rework_requested?: boolean;
}

export async function runVerification(orderId: string): Promise<RunVerificationResponse> {
  return authorizedSend<RunVerificationResponse>(
    `/api/v1/work-orders/${orderId}/verify`,
    { method: "POST" }
  );
}

export async function fetchWorkOrderVerification(
  orderId: string
): Promise<WorkOrderVerification | null> {
  return authorizedSend<WorkOrderVerification | null>(
    `/api/v1/work-orders/${orderId}/verification`
  );
}

export interface EvidencePhoto {
  id: string;
  category: "BEFORE" | "AFTER";
  url: string;
  original_filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  created_at: string;
  uploaded_by_name: string | null;
}

export interface ComplaintMediaItem {
  id: string;
  media_type: string;
  url: string;
  original_filename: string;
  content_type: string;
  created_at: string;
}

export interface WorkOrderEvidence {
  order_id: string;
  order_status: WorkOrderStatus;
  complaint_id: string;
  complaint_title: string | null;
  complaint_description: string | null;
  complaint_category: string | null;
  complaint_media: ComplaintMediaItem[];
  worker_id: string | null;
  worker_name: string | null;
  completed_at: string | null;
  evidence_submitted_at: string | null;
  completion_notes: string | null;
  before_photos: EvidencePhoto[];
  after_photos: EvidencePhoto[];
}

export async function fetchWorkOrderEvidence(
  orderId: string
): Promise<WorkOrderEvidence> {
  return authorizedSend<WorkOrderEvidence>(
    `/api/v1/work-orders/${orderId}/evidence`
  );
}

export async function reviewVerification(
  orderId: string,
  decision: VerificationReviewDecision,
  note?: string
): Promise<VerificationReviewOut> {
  return authorizedSend<VerificationReviewOut>(
    `/api/v1/work-orders/${orderId}/verification/review`,
    { method: "POST", body: { decision, note: note ?? null } }
  );
}