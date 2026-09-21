"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Map as MapIcon, MapPin, RefreshCw } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { WardCivicMap } from "@/components/citizen/ward-civic-map";
import { fetchGeoWards, type WardBoundary, type WardList } from "@/lib/citizen-api";
import { cn } from "@/lib/utils";

interface CivicMapSectionProps {
  registeredWardCode?: string | null;
}

export function CivicMapSection({ registeredWardCode }: CivicMapSectionProps) {
  const [data, setData] = React.useState<WardList | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    React.startTransition(() => {
      setLoading(true);
      setError(null);
    });
    fetchGeoWards()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Could not load ward boundaries.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const retry = () => setTick((t) => t + 1);

  // Only real (non-demo) ward boundaries are shown — demo/dummy geography is
  // never rendered to citizens.
  const realWards = React.useMemo(() => {
    if (!data) return [];
    return data.wards.filter((w) => !w.is_demo);
  }, [data]);

  const geometry = React.useMemo(() => {
    return realWards
      .filter((w) => Array.isArray(w.geometry) && (w.geometry as number[][]).length >= 3)
      .map((w: WardBoundary) => ({
        code: w.code ?? "",
        name: w.name,
        ring: (w.geometry as number[][]) ?? [],
      }));
  }, [realWards]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.05, ease: "easeOut" }}
      aria-label="Your area map"
    >
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapIcon className="h-5 w-5 text-primary-600" />
            Your area
          </CardTitle>
          <CardDescription>
            Real municipal ward boundaries across Pune. Your registered ward is
            highlighted.
          </CardDescription>
        </CardHeader>

        <CardContent className="pt-3">
          {loading ? (
            <Skeleton className="h-72 w-full rounded-2xl" />
          ) : error ? (
            <div className="flex h-72 flex-col items-center justify-center rounded-2xl border border-dashed border-border-strong bg-slate-50 px-6 text-center">
              <MapIcon className="h-8 w-8 text-slate-300" />
              <p className="mt-3 text-sm font-medium text-slate-700">Map unavailable</p>
              <p className="mt-1 text-xs text-slate-500">{error}</p>
              <Button variant="outline" size="sm" className="mt-4 gap-1.5" onClick={retry}>
                <RefreshCw className="h-3.5 w-3.5" />
                Try again
              </Button>
            </div>
          ) : geometry.length === 0 ? (
            <div className="flex h-72 flex-col items-center justify-center rounded-2xl border border-dashed border-border-strong bg-slate-50 px-6 text-center">
              <MapPin className="h-8 w-8 text-slate-300" />
              <p className="mt-3 text-sm font-medium text-slate-700">Boundary data not available</p>
              <p className="mt-1 max-w-sm text-xs text-slate-500">
                Ward boundary geometry could not be loaded. Your ward information is still shown
                below.
              </p>
            </div>
          ) : (
            <WardCivicMap geometry={geometry} registeredWardCode={registeredWardCode} />
          )}

          {realWards.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {realWards.map((w) => {
                const isRegistered = registeredWardCode != null && w.code === registeredWardCode;
                return (
                  <span
                    key={w.ward_id}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
                      isRegistered
                        ? "border-primary-300 bg-primary-50 text-primary-700"
                        : "border-border-soft bg-slate-50 text-slate-600"
                    )}
                  >
                    <MapPin className={cn("h-3 w-3", isRegistered ? "text-primary-600" : "text-slate-400")} />
                    {w.name}
                    {isRegistered && " · your ward"}
                  </span>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
}