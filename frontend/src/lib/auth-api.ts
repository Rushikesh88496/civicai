"use client";

// Client-side API helpers for authentication and session management.
//
// Security model:
// - The short-lived access token is kept in memory only (never persisted).
// - The longer-lived refresh token is stored in localStorage to restore the
//   session on page reload.
// - When an access token is missing/expired the client transparently refreshes
//   it and retries the request.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

const REFRESH_KEY = "ca_refresh";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_email_verified: boolean;
  role: {
    id: string;
    name: string;
    description: string | null;
  };
  // The ward the user registered under (Part 31 — registration is ward-scoped).
  ward: {
    id: string;
    code: string;
    name: string | null;
  } | null;
  profile: {
    phone: string | null;
    address: string | null;
    city: string | null;
    avatar_url: string | null;
    timezone: string | null;
    // Preferred language code (Part 26); one of en/hi/mr or null (English).
    language: string | null;
  };
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

interface AuthResponse {
  user: AuthUser;
  tokens: TokenPair;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;

export function getStoredRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export function setSession(tokens: TokenPair) {
  accessToken = tokens.access_token;
  if (typeof window !== "undefined") {
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  }
}

export function clearSession() {
  accessToken = null;
  if (typeof window !== "undefined") {
    localStorage.removeItem(REFRESH_KEY);
  }
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      0,
      `Cannot reach the CivicAgent API at ${API_BASE_URL}. Is the backend server running?`
    );
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) return null;

  try {
    const res = await apiFetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      clearSession();
      return null;
    }
    const data = (await res.json()) as TokenPair;
    setSession(data);
    return data.access_token;
  } catch {
    clearSession();
    return null;
  }
}

export async function getAccessToken(): Promise<string | null> {
  if (accessToken) return accessToken;
  // Coalesce concurrent refresh attempts.
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export async function authorizedFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  let token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }

  const doFetch = (bearer: string) =>
    apiFetch(path, {
      ...options,
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        Authorization: `Bearer ${bearer}`,
        ...(options.headers || {}),
      },
    });

  let res = await doFetch(token);

  if (res.status === 401) {
    accessToken = null;
    token = await getAccessToken();
    if (token) {
      res = await doFetch(token);
    }
  }

  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export async function readErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail[0]?.msg || "Invalid input.";
    }
  } catch {
    // ignore parse errors
  }
  return res.statusText || "Request failed.";
}

export async function login(
  email: string,
  password: string
): Promise<AuthUser> {
  const res = await apiFetch(`/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const data = (await res.json()) as AuthResponse;
  setSession(data.tokens);
  return data.user;
}

export interface PublicWard {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  is_active: boolean;
}

/** Active wards a new citizen can register under (public, unauthenticated). */
export async function listActiveWards(): Promise<PublicWard[]> {
  const res = await apiFetch("/api/v1/wards");
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  return res.json() as Promise<PublicWard[]>;
}

export async function register(
  fullName: string,
  email: string,
  password: string,
  wardId: string
): Promise<AuthUser> {
  const res = await apiFetch("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ full_name: fullName, email, password, ward_id: wardId }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const data = (await res.json()) as AuthResponse;
  setSession(data.tokens);
  return data.user;
}

export async function fetchMe(): Promise<AuthUser> {
  const data = await authorizedFetch<{ user: AuthUser }>("/api/v1/auth/me");
  return data.user;
}

export interface ProfileUpdate {
  phone?: string | null;
  address?: string | null;
  city?: string | null;
  avatar_url?: string | null;
  timezone?: string | null;
  language?: string | null;
}

export async function updateMyProfile(payload: ProfileUpdate): Promise<ProfileUpdate> {
  return authorizedFetch<ProfileUpdate>("/api/v1/auth/me/profile", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function logout(): Promise<void> {
  const refreshToken = getStoredRefreshToken();
  clearSession();
  if (refreshToken) {
    try {
      await apiFetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Best-effort server revocation; ignore failures.
    }
  }
}

export interface ForgotPasswordResult {
  message: string;
  resetToken?: string | null;
}

export async function forgotPassword(email: string): Promise<ForgotPasswordResult> {
  const res = await apiFetch("/api/v1/auth/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const data = await res.json();
  return { message: data.message, resetToken: data.reset_token };
}

export async function resetPassword(
  token: string,
  newPassword: string
): Promise<string> {
  const res = await apiFetch("/api/v1/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  const data = await res.json();
  return data.message as string;
}