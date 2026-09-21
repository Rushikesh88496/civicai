"use client";

import * as React from "react";
import {
  CheckCircle2,
  CircleDashed,
  Database,
  MapPinOff,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { formatDate } from "@/components/dashboard/format";
import {
  fetchRegistry,
  fetchRegistrySummary,
  registryStatusLabel,
  syncRegistry,
  type RegistryAssetOut,
  type RegistrySummaryOut,
  type RegistryStatus,
} from "@/lib/infrastructure-api";

const statusVariant: Record<RegistryStatus, "success" | "secondary" | "warning" | "destructive"> = {
  FOUND: "success",
  NO_VERIFIED_RECORDS: "secondary",
  PENDING_VERIFICATION: "warning",
  DATA_UNAVAILABLE: "destructive",
};

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50 px-3 py-2">
      <p className="text-lg font-semibold text-slate-900">{value}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}

export function RegistryPanel() {
  const [summary, setSummary] = React.useState<RegistrySummaryOut | null>(null);
  const [items, setItems] = React.useState<RegistryAssetOut[]>([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [syncing, setSyncing] = React.useState(false);
  const [tick, setTick] = React.useState(0);
  const { addToast } = useToast();

  React.useEffect(() => {
    let active = true;
    Promise.all([fetchRegistrySummary(), fetchRegistry({ limit: 20 })])
      .then(([s, l]) => {
        if (!active) return;
        setSummary(s);
        setItems(l.items);
        setTotal(l.total);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load the verified facility registry.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  const runSync = React.useCallback(async () => {
    setSyncing(true);
    try {
      const out = await syncRegistry(false);
      addToast(
        `Registry sync complete: ${out.inserted} inserted, ${out.updated} updated, ` +
          `${out.skipped_duplicate} duplicate, ${out.failed_total} failed in ` +
          `${out.duration_seconds.toFixed(1)}s.`,
        out.failed_total > 0 && out.inserted === 0 ? "error" : "success"
      );
      reload();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Registry sync failed.", "error");
    } finally {
      setSyncing(false);
    }
  }, [addToast, reload]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary-600" />
          <div>
            <CardTitle>Verified facility registry</CardTitle>
            <CardDescription>
              Real facilities (OpenStreetMap) persisted with provenance and a
              data-quality state per record.
            </CardDescription>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={reload} disabled={loading}>
            <RefreshCw className={loading ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
            Refresh
          </Button>
          <Button size="sm" onClick={runSync} disabled={syncing}>
            <Sparkles className={syncing ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
            {syncing ? "Syncing…" : "Sync from OpenStreetMap"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
            <Button variant="outline" size="sm" onClick={reload} className="ml-3">
              Retry
            </Button>
          </div>
        ) : loading && !summary ? (
          <p className="text-sm text-slate-400">Loading registry…</p>
        ) : summary ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Total records" value={summary.total} />
              <Stat label="Verified (FOUND)" value={summary.verified} />
              <Stat label="Pending verification" value={summary.pending} />
              <Stat label="Unlocated" value={summary.unlocated} />
            </div>

            <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-slate-500">
              {Object.entries(summary.by_source).map(([source, count]) => (
                <span key={source}>
                  {source}: <span className="font-medium text-slate-700">{count}</span>
                </span>
              ))}
              {summary.last_verified_at && (
                <span>
                  Last verified:{" "}
                  <span className="font-medium text-slate-700">
                    {formatDate(summary.last_verified_at)}
                  </span>
                </span>
              )}
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-bold uppercase tracking-wide text-gray-500">
                  Registry records
                </p>
                <span className="text-xs text-slate-400">
                  showing {items.length} of {total}
                </span>
              </div>
              {items.length === 0 ? (
                <div className="flex items-center gap-3 rounded-lg border border-dashed border-border-strong p-4 text-sm text-slate-500">
                  <CircleDashed className="h-5 w-5 text-slate-400" />
                  <span>
                    No verified facilities yet. Run <em>Sync from OpenStreetMap</em> to populate
                    the registry with real Pune facilities.
                  </span>
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border border-border-soft">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-3 py-2 font-medium">Facility</th>
                        <th className="px-3 py-2 font-medium">Category</th>
                        <th className="px-3 py-2 font-medium">Ward</th>
                        <th className="px-3 py-2 font-medium">Source</th>
                        <th className="px-3 py-2 font-medium">State</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-soft">
                      {items.map((r) => (
                        <tr key={r.id} className="bg-surface">
                          <td className="px-3 py-2 font-medium text-slate-800">{r.name}</td>
                          <td className="px-3 py-2 text-slate-600">{r.category}</td>
                          <td className="px-3 py-2 text-slate-600">
                            {r.ward_name ? `WARD-${r.ward_name}` : "—"}
                          </td>
                          <td className="px-3 py-2 text-slate-500">
                            {r.source ?? "—"}
                            {r.source_dataset ? ` · ${r.source_dataset}` : ""}
                          </td>
                          <td className="px-3 py-2">
                            <Badge variant={statusVariant[r.verification_status]}>
                              {r.verification_status === "FOUND" ? (
                                <CheckCircle2 className="mr-1 h-3 w-3" />
                              ) : r.verification_status === "NO_VERIFIED_RECORDS" ? (
                                <MapPinOff className="mr-1 h-3 w-3" />
                              ) : (
                                <CircleDashed className="mr-1 h-3 w-3" />
                              )}
                              {registryStatusLabel[r.verification_status]}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}