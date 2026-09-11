"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  CloudSun,
  Loader2,
  RefreshCw,
  ShieldAlert,
  MapPin,
  CloudRain,
  Wind,
  Thermometer,
  Landmark,
  History,
  Database,
  Sparkles,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchAiContext,
  runAiContext,
  type AiContextRun,
} from "@/lib/citizen-api";

interface Props {
  complaintId: string;
}

function fmtTemp(c: number | null): string {
  return c == null ? "—" : `${Math.round(c)}°C`;
}

function fmtDistance(m: number | null): string {
  if (m == null) return "";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function ContextIntelligenceCard({ complaintId }: Props) {
  const [run, setRun] = useState<AiContextRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchAiContext(complaintId)
      .then((r) => {
        if (!cancelled) {
          setRun(r);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load context enrichment."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [complaintId, reloadKey]);

  const runEnrichment = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const resp = await runAiContext(complaintId);
      setReloadKey((k) => k + 1);
      if (resp.status === "FAILED") {
        setError(resp.error || "Context enrichment failed. You can retry.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run context enrichment.");
    } finally {
      setRunning(false);
    }
  }, [complaintId]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-sky-600" /> Context Intelligence
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-4 w-56" />
        </CardContent>
      </Card>
    );
  }

  const result = run?.structured_result ?? null;
  const failed = run?.status === "FAILED";
  const inProgress = running || run?.status === "RUNNING";
  const weather = result?.weather_context;
  const gis = result?.gis_context;
  const historical = result?.historical_context;
  const infra = result?.infrastructure_context;
  const sources = result?.sources ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-sky-600" /> Context Intelligence
        </CardTitle>
        <CardDescription>
          Situational context (weather, locality, history, nearby critical
          infrastructure) to inform triage.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {inProgress && (
          <div className="flex items-center gap-3 rounded-lg border border-sky-100 bg-sky-50 p-3 text-sm text-sky-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Gathering weather, locality and historical context…
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {failed && !result && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-gray-600">
              Context enrichment failed. The complaint is safe and you can retry.
            </p>
            <Button variant="outline" size="sm" onClick={runEnrichment} disabled={running}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {!result && !inProgress && !failed && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              This complaint has not been enriched with situational context yet.
            </p>
            <Button variant="default" size="sm" onClick={runEnrichment} disabled={running}>
              <Sparkles className="mr-1.5 h-4 w-4" /> Understand the situation
            </Button>
          </div>
        )}

        {result && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            {/* Weather */}
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                <CloudSun className="h-3.5 w-3.5" /> Weather
                {weather?.cached && (
                  <span className="ml-auto rounded-full bg-sky-50 px-2 py-0.5 text-[10px] text-sky-600">
                    cached
                  </span>
                )}
              </p>
              {weather?.available ? (
                <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <div>
                    <p className="text-xs text-gray-400">Temperature</p>
                    <p className="flex items-center gap-1 font-medium text-gray-900">
                      <Thermometer className="h-3.5 w-3.5 text-gray-400" />
                      {fmtTemp(weather.temperature_c)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Condition</p>
                    <p className="font-medium capitalize text-gray-900">
                      {weather.condition ?? "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Rainfall</p>
                    <p className="flex items-center gap-1 font-medium text-gray-900">
                      <CloudRain className="h-3.5 w-3.5 text-gray-400" />
                      {(weather.rain_mm ?? weather.precipitation_mm) != null
                        ? `${(weather.rain_mm ?? weather.precipitation_mm)?.toFixed(1)} mm`
                        : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Wind</p>
                    <p className="flex items-center gap-1 font-medium text-gray-900">
                      <Wind className="h-3.5 w-3.5 text-gray-400" />
                      {weather.wind_speed_kmh != null
                        ? `${Math.round(weather.wind_speed_kmh)} km/h`
                        : "—"}
                    </p>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-sm text-gray-500">
                  Weather could not be resolved for this location.
                </p>
              )}
              {weather?.retrieved_at && (
                <p className="mt-2 text-[11px] text-gray-400">
                  retrieved {fmtTime(weather.retrieved_at)}
                </p>
              )}
            </div>

            {/* Locality */}
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                <MapPin className="h-3.5 w-3.5" /> Locality
              </p>
              <div className="mt-2 space-y-1 text-sm">
                {gis?.ward_name && (
                  <p className="font-medium text-gray-900">
                    {gis.ward_name}
                    {gis.ward_code ? ` (${gis.ward_code})` : ""}
                  </p>
                )}
                {gis?.address ? (
                  <p className="text-gray-600">{gis.address}</p>
                ) : (
                  <p className="text-gray-500">Address not resolved.</p>
                )}
                {gis?.ward_is_demo && (
                  <p className="text-[11px] uppercase tracking-wide text-amber-500">
                    {gis.demo_label}
                  </p>
                )}
              </div>
            </div>

            {/* Historical volume */}
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                <History className="h-3.5 w-3.5" /> Historical
              </p>
              <div className="mt-2 flex items-center gap-6 text-sm">
                <div>
                  <p className="text-2xl font-bold text-gray-900">
                    {historical?.total_prior ?? 0}
                  </p>
                  <p className="text-xs text-gray-400">
                    prior complaints within range
                  </p>
                </div>
                {historical?.same_ward_count != null && (
                  <div>
                    <p className="text-2xl font-bold text-gray-900">
                      {historical.same_ward_count}
                    </p>
                    <p className="text-xs text-gray-400">in the same ward</p>
                  </div>
                )}
              </div>
              {historical?.summary && (
                <p className="mt-2 text-sm text-gray-600">{historical.summary}</p>
              )}
            </div>

            {/* Nearby critical infrastructure */}
            <div className="rounded-lg border border-gray-200 p-4">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                <Landmark className="h-3.5 w-3.5" /> Nearby critical
              </p>
              {infra?.available ? (
                <>
                  <div className="mt-2 flex flex-wrap gap-4 text-sm">
                    <div>
                      <p className="text-lg font-bold text-gray-900">
                        {infra.hospitals}
                      </p>
                      <p className="text-xs text-gray-400">hospitals</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-gray-900">
                        {infra.schools}
                      </p>
                      <p className="text-xs text-gray-400">schools</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-gray-900">
                        {infra.bus_stops}
                      </p>
                      <p className="text-xs text-gray-400">bus stops</p>
                    </div>
                  </div>
                  {infra.highlights.length > 0 && (
                    <ul className="mt-3 space-y-1">
                      {infra.highlights.map((h, i) => (
                        <li
                          key={i}
                          className="flex items-center justify-between text-sm text-gray-600"
                        >
                          <span className="flex items-center gap-1.5">
                            <Database className="h-3.5 w-3.5 text-gray-400" />
                            {h.name}
                          </span>
                          <span className="text-xs text-gray-400">
                            {fmtDistance(h.distance_m)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <p className="mt-2 text-sm text-gray-500">
                  No nearby critical locations resolved.
                </p>
              )}
            </div>

            {/* Summary */}
            {result.summary && (
              <p className="text-sm text-gray-700">{result.summary}</p>
            )}

            {/* Provenance */}
            {sources.length > 0 && (
              <div className="rounded-md bg-gray-50 p-3">
                <p className="text-xs font-medium text-gray-500">
                  Data sources
                </p>
                <ul className="mt-1 space-y-0.5">
                  {sources.map((s, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between text-xs text-gray-500"
                    >
                      <span>{s.name}</span>
                      <span>
                        {s.source_type} · {fmtTime(s.retrieved_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={runEnrichment}
                disabled={running}
              >
                <RefreshCw className="mr-1.5 h-4 w-4" /> Re-run
              </Button>
            </div>
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}