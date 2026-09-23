"use client";

import * as React from "react";
import { CheckCircle2, Database, HardHat, RefreshCw } from "lucide-react";
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
  fetchInfrastructureAssets,
  syncInfrastructureAssets,
  type InfrastructureAsset,
} from "@/lib/infrastructure-api";

function countBy<T>(items: T[], key: (item: T) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of items) {
    const k = key(item);
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50 px-3 py-2">
      <p className="text-lg font-semibold text-slate-900">{value}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}

function BucketRows({ buckets }: { buckets: Record<string, number> }) {
  const entries = Object.entries(buckets).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([key, count]) => (
        <span
          key={key}
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
        >
          {key}
          <span className="rounded-full bg-slate-200 px-1.5 font-medium text-slate-800">{count}</span>
        </span>
      ))}
    </div>
  );
}

export function AssetRegistryPanel() {
  const [assets, setAssets] = React.useState<InfrastructureAsset[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [syncing, setSyncing] = React.useState(false);
  const [tick, setTick] = React.useState(0);
  const { addToast } = useToast();

  React.useEffect(() => {
    let active = true;
    fetchInfrastructureAssets()
      .then((list) => {
        if (!active) return;
        setAssets(list);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load the asset registry.");
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
      const out = await syncInfrastructureAssets();
      addToast(
        `Asset registry sync complete: ${out.inserted} inserted, ${out.updated} updated, ` +
          `${out.skipped_duplicate} unchanged, ${out.unlocated} unlocated. ` +
          `Total registered: ${out.registered_total}.`,
        "success"
      );
      reload();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Asset registry sync failed.", "error");
    } finally {
      setSyncing(false);
    }
  }, [addToast, reload]);

  const byCategory = React.useMemo(() => countBy(assets, (a) => a.category), [assets]);
  const byWard = React.useMemo(
    () => countBy(assets, (a) => a.ward_name ? `Ward ${a.ward_name}` : "Unassigned"),
    [assets]
  );
  const byCondition = React.useMemo(
    () => countBy(assets, (a) => (a.condition_note ? "Has note" : "No condition note")),
    [assets]
  );
  const sourced = React.useMemo(() => countBy(assets, (a) => a.source ?? "unsourced"), [assets]);
  const sourceDataset = assets.find((a) => a.source_dataset)?.source_dataset ?? null;
  const wardsCovered = React.useMemo(
    () => Object.keys(byWard).filter((k) => k !== "Unassigned").length,
    [byWard]
  );
  const wardedCount = React.useMemo(
    () => assets.filter((a) => a.ward_id).length,
    [assets]
  );

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary-600" />
          <div>
            <CardTitle>Asset registry</CardTitle>
            <CardDescription>
              Maintainable infrastructure assets for predictive maintenance, registered from the
              real verified facility registry with full provenance.
            </CardDescription>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={reload} disabled={loading}>
            <RefreshCw className={loading ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
            Refresh
          </Button>
          <Button size="sm" onClick={runSync} disabled={syncing}>
            <RefreshCw className={syncing ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
            {syncing ? "Syncing…" : "Sync from facility registry"}
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
        ) : loading && assets.length === 0 ? (
          <p className="text-sm text-slate-400">Loading asset registry…</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <SummaryStat label="Registered assets" value={assets.length} />
              <SummaryStat label="With ward assignment" value={wardedCount} />
              <SummaryStat label="Wards covered" value={wardsCovered} />
              <SummaryStat label="With condition note" value={byCondition["Has note"] ?? 0} />
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">
                  By type
                </p>
                <BucketRows buckets={byCategory} />
              </div>
              <div>
                <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">
                  By ward
                </p>
                <BucketRows buckets={byWard} />
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">
                  Source
                </p>
                <BucketRows buckets={sourced} />
              </div>
              <div>
                <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-gray-500">
                  Condition
                </p>
                <BucketRows buckets={byCondition} />
              </div>
            </div>

            {sourceDataset ? (
              <p className="text-xs text-slate-500">
                Dataset: <span className="font-medium text-slate-700">{sourceDataset}</span>
                {" · "}Registered on {assets.length ? formatDate(assets[assets.length - 1].created_at) : "—"}.
                Installation dates are not part of the source data, so none are set.
              </p>
            ) : null}

            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-bold uppercase tracking-wide text-gray-500">
                  Registered assets
                </p>
                {assets.length > 0 && (
                  <span className="text-xs text-slate-400">
                    showing {assets.length} of {assets.length}
                  </span>
                )}
              </div>
              {assets.length === 0 ? (
                <div className="flex items-center gap-3 rounded-lg border border-dashed border-border-strong p-4 text-sm text-slate-500">
                  <HardHat className="h-5 w-5 text-slate-400" />
                  <span>
                    No real assets registered yet. Run <em>Sync from facility registry</em> to
                    register the maintainable facilities (currently ROAD) from the verified
                    registry. No assets are ever invented.
                  </span>
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border border-border-soft">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-3 py-2 font-medium">Asset</th>
                        <th className="px-3 py-2 font-medium">Category</th>
                        <th className="px-3 py-2 font-medium">Ward</th>
                        <th className="px-3 py-2 font-medium">Registered</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-soft">
                      {assets.slice(0, 100).map((a) => (
                        <tr key={a.id} className="bg-surface">
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-slate-800">{a.name}</span>
                              {a.source === "openstreetmap" ? (
                                <Badge variant="outline">
                                  <CheckCircle2 className="mr-1 h-3 w-3 text-success-600" />
                                  real
                                </Badge>
                              ) : null}
                            </div>
                            {a.source_id ? (
                              <p className="text-xs text-slate-400">source_id: {a.source_id}</p>
                            ) : null}
                          </td>
                          <td className="px-3 py-2 text-slate-600">{a.category}</td>
                          <td className="px-3 py-2 text-slate-600">
                            {a.ward_name ? `Ward ${a.ward_name}` : "—"}
                          </td>
                          <td className="px-3 py-2 text-slate-500">{formatDate(a.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default AssetRegistryPanel;