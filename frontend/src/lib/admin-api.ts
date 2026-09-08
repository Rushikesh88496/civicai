"use client";

import { ApiError, getAccessToken } from "@/lib/auth-api";
import type { SlaPolicy, SlaPolicyIn } from "@/lib/officer-api";

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

async function authorizedGet<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new ApiError(401, "Not authenticated.");
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new ApiError(res.status, await readErrorMessage(res));
  return res.json() as Promise<T>;
}

async function authorizedRequest<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new ApiError(401, "Not authenticated.");
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) throw new ApiError(res.status, await readErrorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PageParams {
  page?: number;
  page_size?: number;
  search?: string;
}

function buildQs(params: object): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  });
  const s = qs.toString();
  return s ? `?${s}` : "";
}

// --------------------------------------------------------------------------- //
// Summary
// --------------------------------------------------------------------------- //

export interface AdminSummary {
  users: number;
  active_users: number;
  roles: number;
  wards: number;
  active_wards: number;
  departments: number;
  field_workers: number;
  representatives: number;
  complaint_categories: number;
  system_settings: number;
  audit_logs: number;
}

export async function fetchAdminSummary(): Promise<AdminSummary> {
  return authorizedGet<AdminSummary>("/api/v1/admin/summary");
}

// --------------------------------------------------------------------------- //
// Users
// --------------------------------------------------------------------------- //

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_email_verified: boolean;
  role: string;
  role_id?: string | null;
  ward_name?: string | null;
  ward_code?: string | null;
  worker_status?: string | null;
  rep_status?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserCreate {
  email: string;
  password: string;
  full_name: string;
  role: string;
  ward_code?: string | null;
  is_email_verified?: boolean;
  department_code?: string | null;
  specialty?: string | null;
  worker_status?: string;
  skill_tags?: string[];
  equipment?: string[];
  rep_title?: string | null;
  rep_status?: string;
}

export interface AdminUserUpdate {
  full_name?: string | null;
  password?: string | null;
  role?: string | null;
  ward_code?: string | null;
  is_active?: boolean | null;
  is_email_verified?: boolean | null;
  department_code?: string | null;
  specialty?: string | null;
  worker_status?: string | null;
  skill_tags?: string[] | null;
  equipment?: string[] | null;
  home_latitude?: number | null;
  home_longitude?: number | null;
  max_active_orders?: number | null;
  rep_title?: string | null;
  rep_status?: string | null;
}

export interface AdminUsersParams extends PageParams {
  role?: string;
  is_active?: boolean;
  ward_code?: string;
}

export async function fetchAdminUsers(params: AdminUsersParams = {}): Promise<Page<AdminUser>> {
  return authorizedGet<Page<AdminUser>>(`/api/v1/admin/users${buildQs(params)}`);
}

export async function fetchAdminUser(id: string): Promise<AdminUser> {
  return authorizedGet<AdminUser>(`/api/v1/admin/users/${id}`);
}

export async function createAdminUser(payload: AdminUserCreate): Promise<AdminUser> {
  return authorizedRequest<AdminUser>("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminUser(id: string, payload: AdminUserUpdate): Promise<AdminUser> {
  return authorizedRequest<AdminUser>(`/api/v1/admin/users/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function disableAdminUser(id: string): Promise<AdminUser> {
  return authorizedRequest<AdminUser>(`/api/v1/admin/users/${id}/disable`, { method: "PATCH" });
}

export async function enableAdminUser(id: string): Promise<AdminUser> {
  return authorizedRequest<AdminUser>(`/api/v1/admin/users/${id}/enable`, { method: "PATCH" });
}

// --------------------------------------------------------------------------- //
// Roles
// --------------------------------------------------------------------------- //

export interface AdminRole {
  id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  user_count: number;
  created_at: string;
}

export interface AdminRoleIn {
  name: string;
  description?: string | null;
}

export interface AdminRoleUpdate {
  description?: string | null;
  is_active?: boolean;
}

export async function fetchAdminRoles(): Promise<AdminRole[]> {
  return authorizedGet<AdminRole[]>("/api/v1/admin/roles");
}

export async function createAdminRole(payload: AdminRoleIn): Promise<AdminRole> {
  return authorizedRequest<AdminRole>("/api/v1/admin/roles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminRole(id: string, payload: AdminRoleUpdate): Promise<AdminRole> {
  return authorizedRequest<AdminRole>(`/api/v1/admin/roles/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Wards
// --------------------------------------------------------------------------- //

export interface AdminWard {
  id: string;
  name: string;
  code: string;
  description?: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AdminWardIn {
  name: string;
  code: string;
  description?: string | null;
}

export interface AdminWardUpdate {
  name?: string | null;
  description?: string | null;
  is_active?: boolean | null;
}

export interface AdminWardsParams extends PageParams {
  is_active?: boolean;
}

export async function fetchAdminWards(params: AdminWardsParams = {}): Promise<Page<AdminWard>> {
  return authorizedGet<Page<AdminWard>>(`/api/v1/admin/wards${buildQs(params)}`);
}

export async function createAdminWard(payload: AdminWardIn): Promise<AdminWard> {
  return authorizedRequest<AdminWard>("/api/v1/admin/wards", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminWard(id: string, payload: AdminWardUpdate): Promise<AdminWard> {
  return authorizedRequest<AdminWard>(`/api/v1/admin/wards/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Departments
// --------------------------------------------------------------------------- //

export interface AdminDepartment {
  id: string;
  name: string;
  code: string;
  description?: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AdminDepartmentIn {
  name: string;
  code: string;
  description?: string | null;
}

export interface AdminDepartmentUpdate {
  name?: string | null;
  description?: string | null;
  is_active?: boolean | null;
}

export interface AdminDepartmentsParams extends PageParams {
  is_active?: boolean;
}

export async function fetchAdminDepartments(
  params: AdminDepartmentsParams = {}
): Promise<Page<AdminDepartment>> {
  return authorizedGet<Page<AdminDepartment>>(`/api/v1/admin/departments${buildQs(params)}`);
}

export async function createAdminDepartment(payload: AdminDepartmentIn): Promise<AdminDepartment> {
  return authorizedRequest<AdminDepartment>("/api/v1/admin/departments", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminDepartment(
  id: string,
  payload: AdminDepartmentUpdate
): Promise<AdminDepartment> {
  return authorizedRequest<AdminDepartment>(`/api/v1/admin/departments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Field workers
// --------------------------------------------------------------------------- //

export interface AdminFieldWorker {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  user_active: boolean;
  department_name?: string | null;
  department_code?: string | null;
  specialty?: string | null;
  status: string;
  skill_tags: string[];
  equipment: string[];
  home_latitude?: number | null;
  home_longitude?: number | null;
  max_active_orders?: number | null;
  created_at: string;
}

export interface AdminFieldWorkerUpdate {
  department_code?: string | null;
  specialty?: string | null;
  status?: string | null;
  skill_tags?: string[] | null;
  equipment?: string[] | null;
  home_latitude?: number | null;
  home_longitude?: number | null;
  max_active_orders?: number | null;
}

export interface AdminWorkersParams extends PageParams {
  department_code?: string;
  status?: string;
}

export async function fetchAdminFieldWorkers(
  params: AdminWorkersParams = {}
): Promise<Page<AdminFieldWorker>> {
  return authorizedGet<Page<AdminFieldWorker>>(`/api/v1/admin/field-workers${buildQs(params)}`);
}

export async function updateAdminFieldWorker(
  id: string,
  payload: AdminFieldWorkerUpdate
): Promise<AdminFieldWorker> {
  return authorizedRequest<AdminFieldWorker>(`/api/v1/admin/field-workers/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Ward representatives
// --------------------------------------------------------------------------- //

export interface AdminRepresentative {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  user_active: boolean;
  ward_name?: string | null;
  ward_code?: string | null;
  title?: string | null;
  status: string;
  created_at: string;
}

export interface AdminRepresentativeUpdate {
  ward_code?: string | null;
  title?: string | null;
  status?: string | null;
}

export interface AdminRepsParams extends PageParams {
  ward_code?: string;
  status?: string;
}

export async function fetchAdminRepresentatives(
  params: AdminRepsParams = {}
): Promise<Page<AdminRepresentative>> {
  return authorizedGet<Page<AdminRepresentative>>(`/api/v1/admin/representatives${buildQs(params)}`);
}

export async function updateAdminRepresentative(
  id: string,
  payload: AdminRepresentativeUpdate
): Promise<AdminRepresentative> {
  return authorizedRequest<AdminRepresentative>(`/api/v1/admin/representatives/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Complaint categories
// --------------------------------------------------------------------------- //

export interface AdminComplaintCategory {
  id: string;
  code: string;
  label: string;
  description?: string | null;
  is_active: boolean;
  sort_order: number;
  created_at: string;
}

export interface AdminComplaintCategoryIn {
  code: string;
  label: string;
  description?: string | null;
  sort_order?: number;
}

export interface AdminComplaintCategoryUpdate {
  label?: string | null;
  description?: string | null;
  is_active?: boolean | null;
  sort_order?: number | null;
}

export async function fetchAdminComplaintCategories(): Promise<AdminComplaintCategory[]> {
  return authorizedGet<AdminComplaintCategory[]>("/api/v1/admin/complaint-categories");
}

export async function createAdminComplaintCategory(
  payload: AdminComplaintCategoryIn
): Promise<AdminComplaintCategory> {
  return authorizedRequest<AdminComplaintCategory>("/api/v1/admin/complaint-categories", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminComplaintCategory(
  id: string,
  payload: AdminComplaintCategoryUpdate
): Promise<AdminComplaintCategory> {
  return authorizedRequest<AdminComplaintCategory>(`/api/v1/admin/complaint-categories/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Priority weights
// --------------------------------------------------------------------------- //

export interface AdminPriorityWeight {
  id: string;
  key: string;
  label: string;
  weight: number;
  is_active: boolean;
  updated_at: string;
}

export interface AdminPriorityWeightIn {
  key: string;
  label: string;
  weight: number;
}

export interface AdminPriorityWeightUpdate {
  label?: string | null;
  weight?: number | null;
  is_active?: boolean | null;
}

export async function fetchAdminPriorityWeights(): Promise<AdminPriorityWeight[]> {
  return authorizedGet<AdminPriorityWeight[]>("/api/v1/admin/priority-weights");
}

export async function createAdminPriorityWeight(
  payload: AdminPriorityWeightIn
): Promise<AdminPriorityWeight> {
  return authorizedRequest<AdminPriorityWeight>("/api/v1/admin/priority-weights", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminPriorityWeight(
  id: string,
  payload: AdminPriorityWeightUpdate
): Promise<AdminPriorityWeight> {
  return authorizedRequest<AdminPriorityWeight>(`/api/v1/admin/priority-weights/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// SLA policies (admin-scope CRUD)
// --------------------------------------------------------------------------- //

export async function fetchAdminSlaPolicies(): Promise<SlaPolicy[]> {
  return authorizedGet<SlaPolicy[]>("/api/v1/admin/sla/policies");
}

export async function createAdminSlaPolicy(payload: SlaPolicyIn): Promise<SlaPolicy> {
  return authorizedRequest<SlaPolicy>("/api/v1/admin/sla/policies", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAdminSlaPolicy(id: string, payload: SlaPolicyIn): Promise<SlaPolicy> {
  return authorizedRequest<SlaPolicy>(`/api/v1/admin/sla/policies/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteAdminSlaPolicy(id: string): Promise<void> {
  return authorizedRequest<void>(`/api/v1/admin/sla/policies/${id}`, { method: "DELETE" });
}

// --------------------------------------------------------------------------- //
// System configuration
// --------------------------------------------------------------------------- //

export interface ConfigItem {
  key: string;
  label: string;
  category: string;
  value_type: string;
  is_secret: boolean;
  is_editable: boolean;
  configured: boolean;
  masked?: string | null;
  value?: string | number | boolean | null;
  source: string;
  updated_at?: string | null;
}

export interface ConfigTest {
  key: string;
  configured: boolean;
  reachable: boolean;
  message: string;
  latency_ms?: number | null;
  detail?: Record<string, unknown> | null;
}

export async function fetchAdminConfig(): Promise<ConfigItem[]> {
  return authorizedGet<ConfigItem[]>("/api/v1/admin/config");
}

export async function updateAdminConfig(
  key: string,
  value: string | number | boolean | null
): Promise<ConfigItem> {
  return authorizedRequest<ConfigItem>(`/api/v1/admin/config/${key}`, {
    method: "PATCH",
    body: JSON.stringify({ value }),
  });
}

export async function clearAdminConfig(key: string): Promise<ConfigItem> {
  return authorizedRequest<ConfigItem>(`/api/v1/admin/config/${key}`, { method: "DELETE" });
}

export async function testGroqConfig(): Promise<ConfigTest> {
  return authorizedRequest<ConfigTest>("/api/v1/admin/config/groq/test", { method: "POST" });
}

// --------------------------------------------------------------------------- //
// Audit logs
// --------------------------------------------------------------------------- //

export interface AuditLog {
  id: string;
  actor_id?: string | null;
  actor_email?: string | null;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  ip_address?: string | null;
  created_at: string;
}

export interface AdminAuditParams extends PageParams {
  action?: string;
  entity_type?: string;
}

export async function fetchAdminAuditLogs(params: AdminAuditParams = {}): Promise<Page<AuditLog>> {
  return authorizedGet<Page<AuditLog>>(`/api/v1/admin/audit-logs${buildQs(params)}`);
}