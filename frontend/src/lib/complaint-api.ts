"use client";

// Client-side helpers for uploading complaint media and submitting a civic
// complaint (Part 4 multimodal flow). Reuses the access-token machinery from
// auth-api (in-memory token + transparent refresh).

import { ApiError, authorizedFetch, getAccessToken } from "@/lib/auth-api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export interface ComplaintMedia {
  id: string;
  media_type: "IMAGE" | "VIDEO";
  original_filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
  created_at: string;
}

export interface ComplaintLocationInput {
  latitude: number;
  longitude: number;
  address?: string | null;
  source: "gps" | "manual";
  geopoint_denied: boolean;
  // Device-reported GPS horizontal accuracy in metres (Part 31).
  accuracy_m?: number | null;
}

export interface ComplaintCreateInput {
  description: string;
  category: string;
  media_ids: string[];
  location?: ComplaintLocationInput | null;
}

export interface ComplaintCreateResult {
  id: string;
  category: string;
  title: string;
  description: string | null;
  location: string | null;
  priority: string;
  status: string;
  user_id: string;
  created_at: string;
  media: ComplaintMedia[];
}

async function getAuthHeader(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  return { Authorization: `Bearer ${token}` };
}

export interface UploadOptions {
  onProgress?: (percent: number) => void;
}

/** Upload a single image or short video; returns the stored media record. */
export async function uploadMedia(
  file: File,
  options: UploadOptions = {}
): Promise<ComplaintMedia> {
  const headers = await getAuthHeader();

  // Use XMLHttpRequest to surface upload progress (fetch has no progress event).
  return new Promise<ComplaintMedia>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/v1/complaints/media`);
    xhr.setRequestHeader("Authorization", headers.Authorization);

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && options.onProgress) {
        options.onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as ComplaintMedia);
        } catch {
          reject(new ApiError(xhr.status, "Malformed server response."));
        }
      } else if (xhr.status === 0) {
        reject(new ApiError(0, "Network error. Check your connection."));
      } else {
        let message = "Upload failed.";
        try {
          const body = JSON.parse(xhr.responseText);
          if (typeof body?.detail === "string") message = body.detail;
        } catch {
          // fall back to default message
        }
        reject(new ApiError(xhr.status, message));
      }
    });

    xhr.addEventListener("error", () => {
      reject(new ApiError(0, "Network error. Please retry."));
    });
    xhr.addEventListener("abort", () => {
      reject(new ApiError(0, "Upload aborted."));
    });

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

/** Submit a complaint referencing already-uploaded media ids. */
export async function submitComplaint(
  payload: ComplaintCreateInput
): Promise<ComplaintCreateResult> {
  return authorizedFetch<ComplaintCreateResult>("/api/v1/complaints", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}