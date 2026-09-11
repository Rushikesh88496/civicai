"use client";

import * as React from "react";
import {
  Award,
  Building2,
  Home,
  Loader2,
  MapPin,
  ShieldCheck,
  Sparkles,
  UserRound,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Avatar } from "@/components/ui/avatar";
import { initials } from "@/components/dashboard/format";
import { useAuth } from "@/components/auth/auth-provider";
import {
  fetchWorkerProfile,
  type WorkerProfile,
} from "@/lib/field-worker-api";

function InfoRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-border-soft bg-slate-50/60 px-3 py-2.5 text-sm">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface text-slate-400 shadow-sm">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</p>
        <p className="truncate font-medium text-slate-800">{value ?? "—"}</p>
      </div>
    </div>
  );
}

function Chip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-lg border border-border-soft bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm">
      {label}
    </span>
  );
}

export default function FieldWorkerProfilePage() {
  const { user } = useAuth();
  const [profile, setProfile] = React.useState<WorkerProfile | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    fetchWorkerProfile()
      .then((p) => {
        if (!cancelled) {
          setProfile(p);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Could not load your profile.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  if (error && !profile) {
    return (
      <ErrorState
        title="Could not load your profile"
        description={error}
        action={
          <Button onClick={() => setReloadKey((k) => k + 1)} variant="outline">
            Try Again
          </Button>
        }
      />
    );
  }

  const wardName = profile?.ward_name
    ? `${profile.ward_name}${profile.ward_code ? ` (${profile.ward_code})` : ""}`
    : profile?.ward_code ?? null;
  const department = profile?.department_name
    ? `${profile.department_name}${profile.department_code ? ` · ${profile.department_code}` : ""}`
    : profile?.department_code ?? null;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Profile</h1>
        <p className="mt-0.5 text-sm text-slate-500">Your field worker identity.</p>
      </div>

      {loading && !profile ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      ) : (
        <>
          <section className="relative overflow-hidden rounded-xl border border-border-soft bg-surface p-5 text-center shadow-sm">
            <div className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-primary-50 to-transparent" aria-hidden />
            <div className="relative">
              <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-primary-100 ring-4 ring-primary-50">
                <Avatar
                  size="lg"
                  fallback={initials(profile?.full_name || user?.full_name)}
                  src={user?.profile.avatar_url || undefined}
                  alt={profile?.full_name || "Field Worker"}
                />
              </div>
              <h2 className="mt-3 text-lg font-semibold tracking-tight text-slate-900">
                {profile?.full_name ?? user?.full_name ?? "Field Worker"}
              </h2>
              <p className="text-sm text-slate-500">{profile?.email ?? user?.email}</p>
              <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Field Worker
                </span>
                {profile?.status && (
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${
                      profile.status === "ACTIVE"
                        ? "bg-success-100 text-success-700"
                        : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {profile.status === "ACTIVE" ? "Active" : profile.status}
                  </span>
                )}
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-900">Assignment details</h3>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <InfoRow icon={<Building2 className="h-4 w-4" />} label="Department" value={department} />
              <InfoRow icon={<Home className="h-4 w-4" />} label="Ward" value={wardName} />
              {profile?.specialty && (
                <InfoRow icon={<Award className="h-4 w-4" />} label="Specialty" value={profile.specialty} />
              )}
              {profile?.home_latitude != null && profile?.home_longitude != null && (
                <InfoRow
                  icon={<MapPin className="h-4 w-4" />}
                  label="Base location"
                  value={
                    profile.base_location
                      ? `${profile.base_location} (${profile.home_latitude.toFixed(4)}, ${profile.home_longitude.toFixed(4)})`
                      : `${profile.home_latitude.toFixed(4)}, ${profile.home_longitude.toFixed(4)}`
                  }
                />
              )}
            </div>
          </section>

          {(profile?.skill_tags.length || profile?.equipment.length) ? (
            <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-900">Skills & equipment</h3>
              {profile?.skill_tags.length ? (
                <div className="mt-3">
                  <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
                    <Sparkles className="h-3.5 w-3.5" /> Skills
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {profile.skill_tags.map((s) => (
                      <Chip key={s} label={s} />
                    ))}
                  </div>
                </div>
              ) : null}
              {profile?.equipment.length ? (
                <div className="mt-4">
                  <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
                    <Wrench className="h-3.5 w-3.5" /> Equipment
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {profile.equipment.map((e) => (
                      <Chip key={e} label={e} />
                    ))}
                  </div>
                </div>
              ) : null}
              {profile && profile.max_active_orders > 0 && (
                <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-slate-500">
                  <UserRound className="h-3.5 w-3.5" />
                  Max active jobs: {profile.max_active_orders}
                </p>
              )}
            </section>
          ) : null}

          <p className="text-center text-[11px] text-slate-400">
            This information is managed by your administrator and cannot be edited from this app.
          </p>
        </>
      )}
    </div>
  );
}