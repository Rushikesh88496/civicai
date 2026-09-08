"use client";

// Part 26: supported language metadata for the CivicAI language selector.
// Mirrors the backend GET /api/v1/languages payload and the LanguageCode enum
// (en/hi/mr) so the selector never guesses an unsupported code.

export interface LanguageOption {
  code: string;
  name: string;
  native_name: string;
  default?: boolean;
}

export const DEFAULT_LANGUAGE = "en";

// Static fallback matching the backend /languages response (used only if the
// live fetch fails so the selector still renders).
export const STATIC_LANGUAGES: LanguageOption[] = [
  { code: "en", name: "English", native_name: "English", default: true },
  { code: "hi", name: "Hindi", native_name: "हिन्दी" },
  { code: "mr", name: "Marathi", native_name: "मराठी" },
];

export async function fetchLanguages(): Promise<LanguageOption[]> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const res = await fetch(`${base}/api/v1/languages`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error("Unable to load supported languages.");
  }
  return (await res.json()) as LanguageOption[];
}