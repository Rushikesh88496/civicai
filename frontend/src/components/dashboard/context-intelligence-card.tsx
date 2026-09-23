"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  CloudSun,
  Loader2,
  RefreshCw,
  ShieldAlert,
  MapPin,
  Building2,
  History,
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

interface TileProps {
  icon: React.ElementType;
  title: string;
  big?: string | number | null;
  caption?: string | null;
  sub?: React.ReactNode;
  chip?: React.ReactNode;
}

function Tile({ icon: Icon, title, big, caption, sub, chip }: TileProps) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          <Icon className="h-3.5 w-3.5" />
          {title}
        </span>
        {chip}
      </div>
      <div className="mt-2">
        {big != null ? (
          <p className="text-xl font-bold leading-tight tracking-tight text-slate-900">
            {big}
          </p>
        ) : (
          <p className="text-sm font-medium text-slate-500">
            Data unavailable
          </p>
        )}
        {caption != null && (
          <p className="mt-0.5 text-xs leading-snug text-slate-500">{caption}</p>
        )}
        {sub}
      </div>
    </div>
  );
}

export function ContextIntelligenceCard({ complaintId }: Props) {
  const [run, setRun] = useState<AiContextRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    fetchAiContext(complaintId)
      .then((r) => {
        if (cancelled) return;
        setRun(r);
        setError(null);
        if (r !== null && r.status === "RUNNING") {
          timer = setTimeout(() => setReloadKey((k) => k + 1), 2500);
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
      if (timer) clearTimeout(timer);
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
            <Sparkles className="h-4 w-4 text-ai-600" /> Context Intelligence
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
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

  const infraCtx = infra;
  const infraCount =
    infraCtx?.available != null ? infraCtx.total_nearby : null;

  // Status-aware infrastructure tile. New runs carry an explicit
  // available / empty / unavailable status from the geo service; older runs
  // degrade to the legacy flags.
  const infraStatus = infraCtx?.status;
  const infraBig =
    infraCtx != null && infraStatus !== "unavailable" ? infraCount : null;
  let infraCaption: string | null = null;
  if (infraStatus === "empty") {
    infraCaption = "No mapped infrastructure within 500 m.";
  } else if (infraStatus === "unavailable") {
    infraCaption = "Nearby infrastructure data temporarily unavailable.";
  } else if (infraCtx != null && infraStatus === "available") {
    infraCaption = `${infraCtx.hospitals ?? 0} hospitals · ${infraCtx.schools ?? 0} schools · ${infraCtx.bus_stops ?? 0} bus stops`;
    const emergency =
      (infraCtx.police_stations ?? 0) + (infraCtx.fire_stations ?? 0);
    if (emergency > 0) infraCaption += ` · ${emergency} police/fire`;
  } else if (infraCtx?.available) {
    infraCaption = `${infraCtx.hospitals ?? 0} hospitals · ${infraCtx.schools ?? 0} schools · ${infraCtx.bus_stops ?? 0} bus stops`;
  }
  const showHighlights = Boolean(
    infraCtx &&
      ((infraStatus === "available" && infraCtx.highlights.length > 0) ||
        (!infraStatus && infraCtx.available))
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-ai-600" /> Context Intelligence
        </CardTitle>
        <CardDescription>
          Weather, locality, history and nearby critical assets.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {inProgress && (
          <div className="flex items-center gap-3 rounded-lg border border-ai-100 bg-ai-50 p-2.5 text-sm text-ai-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Gathering weather, locality and historical context…
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-danger-100 bg-danger-50 p-2.5 text-sm text-danger-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
            <Button variant="outline" size="sm" className="ml-auto" onClick={runEnrichment} disabled={running}>
              <RefreshCw className="h-3.5 w-3.5" /> Retry
            </Button>
          </div>
        )}

        {failed && !result && !error && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-slate-600">
              Context enrichment failed. The complaint is safe and you can retry.
            </p>
            <Button variant="outline" size="sm" onClick={runEnrichment} disabled={running}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {!result && !inProgress && !failed && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-slate-500">
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
            className="space-y-3"
          >
            <div className="grid grid-cols-2 gap-3">
              <Tile
                icon={CloudSun}
                title="Weather"
                big={weather?.available ? fmtTemp(weather.temperature_c) : null}
                caption={
                  weather?.available
                    ? weather?.condition
                      ? weather.condition[0].toUpperCase() + weather.condition.slice(1)
                      : null
                    : null
                }
                chip={
                  weather?.cached ? (
                    <span className="rounded-full bg-ai-50 px-1.5 py-0.5 text-[10px] font-medium text-ai-600">
                      cached
                    </span>
                  ) : undefined
                }
                sub={
                  weather?.available ? (
                    <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-400">
                      {weather.rain_mm != null || weather.precipitation_mm != null ? (
                        <span>
                          {(weather.rain_mm ?? weather.precipitation_mm)?.toFixed(1)}mm
                        </span>
                      ) : null}
                      {weather.wind_speed_kmh != null ? (
                        <span>{Math.round(weather.wind_speed_kmh)} km/h</span>
                      ) : null}
                      {weather.retrieved_at ? (
                        <span>· {fmtTime(weather.retrieved_at)}</span>
                      ) : null}
                    </div>
                  ) : null
                }
              />
              {weather && !weather.available && !inProgress && (
                <div className="flex flex-col gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] leading-snug text-amber-700">
                      Weather could not be fetched during the last enrichment
                      run.
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={runEnrichment}
                      disabled={running}
                      className="shrink-0"
                    >
                      <RefreshCw className="mr-1 h-3 w-3" /> Retry
                    </Button>
                  </div>
                </div>
              )}

              <Tile
                icon={MapPin}
                title="Area"
                big={
                  gis?.ward_name || gis?.address
                    ? gis.ward_name || gis.address
                    : null
                }
                caption={
                  gis?.ward_name && gis?.address
                    ? gis.address
                    : gis?.ward_is_demo
                      ? gis.demo_label
                      : null
                }
              />

              <Tile
                icon={Building2}
                title="Infrastructure"
                big={infraBig}
                caption={infraCaption}
                sub={
                  showHighlights ? (
                    <ul className="mt-1 space-y-0.5">
                      {infraCtx!.highlights.slice(0, 2).map((h, i) => (
                        <li
                          key={i}
                          className="flex items-center justify-between text-[11px] text-slate-400"
                        >
                          <span className="truncate">{h.name}</span>
                          <span className="ml-2 shrink-0">
                            {fmtDistance(h.distance_m)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null
                }
              />

              <Tile
                icon={History}
                title="History"
                big={
                  historical?.total_prior != null ? historical.total_prior : null
                }
                caption={
                  historical?.total_prior != null
                    ? `prior complaints${historical.same_ward_count != null ? ` · ${historical.same_ward_count} in ward` : ""}`
                    : null
                }
              />
            </div>

            {result.summary && (
              <p className="text-sm leading-relaxed text-slate-600">
                {result.summary}
              </p>
            )}

            {sources.length > 0 && (
              <div className="rounded-md bg-slate-50 p-2.5">
                <p className="text-xs font-medium text-slate-500">Data sources</p>
                <ul className="mt-1 space-y-0.5">
                  {sources.map((s, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between text-xs text-slate-500"
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