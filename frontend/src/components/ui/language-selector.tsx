"use client";

import * as React from "react";
import { Languages } from "lucide-react";
import { useAuth } from "@/components/auth/auth-provider";
import { updateMyProfile } from "@/lib/auth-api";
import { Select } from "@/components/ui/select";

import {
  DEFAULT_LANGUAGE,
  STATIC_LANGUAGES,
  fetchLanguages,
  type LanguageOption,
} from "@/lib/i18n";

// Part 26: global language-preference selector. Persists the choice to the
// user's profile (PATCH /auth/me/profile) and refreshes the auth context so the
// rest of the app (assistant, notifications, classification) uses the new
// preferred language. Renders as a compact globe + dropdown for non-English
// options only and hides entirely for guests.

export function LanguageSelector() {
  const { user, refreshUser } = useAuth();
  const [languages, setLanguages] = React.useState<LanguageOption[]>(
    STATIC_LANGUAGES
  );
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const preferred = user?.profile.language ?? DEFAULT_LANGUAGE;

  React.useEffect(() => {
    let active = true;
    fetchLanguages()
      .then((opts) => {
        if (active && opts.length > 0) setLanguages(opts);
      })
      .catch(() => {
        // Keep the static fallback so the selector still renders.
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const code = event.target.value;
    if (!code || code === preferred) return;
    setSaving(true);
    setError(null);
    try {
      await updateMyProfile({ language: code === DEFAULT_LANGUAGE ? null : code });
      await refreshUser();
    } catch {
      setError("Could not save language preference.");
    } finally {
      setSaving(false);
    }
  }

  if (!user) return null;

  return (
    <div className="relative flex items-center">
      <Languages className="pointer-events-none absolute left-2.5 h-4 w-4 text-gray-500" aria-hidden="true" />
      <Select
        aria-label="Preferred language"
        className="w-36 pl-8"
        value={preferred}
        onChange={handleChange}
        disabled={saving}
      >
        {languages.map((lang) => (
          <option key={lang.code} value={lang.code}>
            {(lang.native_name || lang.name).length > 0
              ? lang.native_name || lang.name
              : lang.name}
          </option>
        ))}
      </Select>
      {error ? (
        <span className="sr-only">{error}</span>
      ) : null}
    </div>
  );
}