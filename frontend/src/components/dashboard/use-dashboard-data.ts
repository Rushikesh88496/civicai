"use client";

import * as React from "react";
import { fetchDashboard, type DashboardData } from "@/lib/citizen-api";

interface UseDashboardDataResult {
  data: DashboardData | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useDashboardData(): UseDashboardDataResult {
  const [data, setData] = React.useState<DashboardData | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchDashboard()
      .then((result) => {
        if (active) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!active) return;
        const message = err instanceof Error ? err.message : "Failed to load dashboard.";
        setError(message);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  return { data, loading, error, reload };
}