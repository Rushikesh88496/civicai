"use client";

import * as React from "react";
import { RefreshCw, Download, FilterX, BarChart3, Flame } from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { categoryLabel } from "@/components/dashboard/format";
import { fetchGeoWards, type WardBoundary } from "@/lib/citizen-api";
import {
  fetchAnalyticsOverview,
  fetchAnalyticsHeatmap,
  downloadAnalyticsCsv,
  ANALYTICS_CATEGORIES,
  ANALYTICS_DEPARTMENTS,
  ANALYTICS_PRIORITIES,
  type AnalyticsFilters,
  type AnalyticsOverview as OverviewData,
  type HeatmapOut,
} from "@/lib/analytics-api";
import { AnalyticsHeatmap } from "@/components/analytics/civic-analytics-heatmap";

const PRIORITY_LABELS: Record<string, string> = {
  P1_CRITICAL: "P1 Critical",
  P2_HIGH: "P2 High",
  P3_MEDIUM: "P3 Medium",
  P4_LOW: "P4 Low",
};

const BLUE = "#2563eb";
const GREEN = "#10b981";
const AMBER = "#f59e0b";
const RED = "#ef4444";
const VIOLET = "#7c3aed";
const SLATE = "#64748b";

const PIE_COLORS = [BLUE, GREEN, AMBER, VIOLET, RED, SLATE, "#0891b2", "#db2777"];

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value.toFixed(1)}%`;
}

function tickPeriod(value: string): string {
  if (/^\d{4}-\d{2}$/.test(value)) {
    const [year, month] = value.split("-");
    const date = new Date(Number(year), Number(month) - 1, 1);
    return date.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function KpiCard({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: "blue" | "red" | "orange" | "green" | "yellow" | "violet";
  hint?: string;
}) {
  const toneClass =
    tone === "red"
      ? "text-danger-600"
      : tone === "orange"
        ? "text-warning-600"
        : tone === "green"
          ? "text-success-600"
          : tone === "yellow"
            ? "text-warning-600"
            : tone === "violet"
              ? "text-ai-600"
              : "text-primary-600";
  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={cn("mt-1 text-2xl font-bold", toneClass)}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-400">{hint}</div> : null}
    </Card>
  );
}

function EmptyOverview() {
  return (
    <EmptyState
      icon={<BarChart3 className="h-8 w-8 text-slate-400" />}
      title="No data in this range"
      description="No complaints match the current filters. Try widening the date range or clearing filters."
    />
  );
}

export function CivicAnalytics() {
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");
  const [wardId, setWardId] = React.useState("");
  const [department, setDepartment] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [priority, setPriority] = React.useState("");

  const [wards, setWards] = React.useState<WardBoundary[]>([]);
  const [overview, setOverview] = React.useState<OverviewData | null>(null);
  const [heatmap, setHeatmap] = React.useState<HeatmapOut | null>(null);

  const [loading, setLoading] = React.useState(true);
  const [exporting, setExporting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    fetchGeoWards()
      .then((data) => setWards(data.wards ?? []))
      .catch(() => setWards([]));
  }, []);

  const resolveFilters = React.useCallback((): AnalyticsFilters => {
    const filters: AnalyticsFilters = {};
    if (dateFrom) filters.date_from = `${dateFrom}T00:00:00+00:00`;
    if (dateTo) filters.date_to = `${dateTo}T23:59:59+00:00`;
    if (wardId) filters.ward_id = wardId;
    if (department) filters.department = department;
    if (category) filters.category = category;
    if (priority) filters.priority = priority;
    return filters;
  }, [dateFrom, dateTo, wardId, department, category, priority]);

  React.useEffect(() => {
    let active = true;
    const filters = resolveFilters();
    Promise.all([fetchAnalyticsOverview(filters), fetchAnalyticsHeatmap(filters)])
      .then(([o, h]) => {
        if (!active) return;
        setError(null);
        setOverview(o);
        setHeatmap(h);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load civic analytics.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick, resolveFilters]);

  const reload = React.useCallback(() => {
    setLoading(true);
    setTick((t) => t + 1);
  }, []);

  const clearFilters = React.useCallback(() => {
    setDateFrom("");
    setDateTo("");
    setWardId("");
    setDepartment("");
    setCategory("");
    setPriority("");
  }, []);

  const handleExport = async () => {
    setExporting(true);
    try {
      await downloadAnalyticsCsv(resolveFilters());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export analytics CSV.");
    } finally {
      setExporting(false);
    }
  };

  const hasFilters =
    Boolean(dateFrom) || Boolean(dateTo) || Boolean(wardId) || Boolean(department) || Boolean(category) || Boolean(priority);
  const k = overview?.kpis;
  const charts = overview?.charts;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Civic Analytics</h1>
          <p className="text-sm text-slate-500">
            Complaint trends, operational performance, SLA compliance, and citizen satisfaction.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleExport} disabled={exporting}>
            <Download className="mr-2 h-4 w-4" />
            {exporting ? "Exporting…" : "Export CSV"}
          </Button>
          <Button variant="outline" onClick={reload}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <Card className="p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">From</label>
            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} aria-label="Date from" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">To</label>
            <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} aria-label="Date to" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Ward</label>
            <Select value={wardId} onChange={(e) => setWardId(e.target.value)} aria-label="Ward">
              <option value="">All wards</option>
              {wards.map((ward) => (
                <option key={ward.ward_id} value={ward.ward_id}>
                  {ward.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Department</label>
            <Select value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Department">
              <option value="">All departments</option>
              {ANALYTICS_DEPARTMENTS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Category</label>
            <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
              <option value="">All categories</option>
              {ANALYTICS_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Priority</label>
            <Select value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority">
              <option value="">All priorities</option>
              {ANALYTICS_PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-400">
            {hasFilters ? "Filters are applied to every metric below." : "Showing all complaints."}
          </p>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <FilterX className="mr-2 h-4 w-4" />
              Clear filters
            </Button>
          )}
        </div>
      </Card>

      {loading ? (
        <LoadingState message="Crunching the numbers…" />
      ) : error ? (
        <ErrorState
          title="Unable to load analytics"
          description={error}
          action={
            <Button variant="outline" onClick={reload}>
              Retry
            </Button>
          }
        />
      ) : !k ? (
        <EmptyOverview />
      ) : (
        <>
          {/* KPI grid */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <KpiCard label="Total Complaints" value={k.total_complaints.toLocaleString()} tone="blue" />
            <KpiCard
              label="Resolution Rate"
              value={formatPercent(k.resolution_rate)}
              tone="green"
              hint={`${k.resolved.toLocaleString()} resolved`}
            />
            <KpiCard
              label="Avg Response Time"
              value={formatDuration(k.response_seconds_avg)}
              tone="orange"
              hint={`median ${formatDuration(k.response_seconds_median)} · n=${k.response_count}`}
            />
            <KpiCard
              label="Avg Resolution Time"
              value={formatDuration(k.resolution_seconds_avg)}
              tone="violet"
              hint={`median ${formatDuration(k.resolution_seconds_median)} · n=${k.resolution_count}`}
            />
            <KpiCard
              label="SLA Compliance"
              value={formatPercent(k.sla_compliance_rate)}
              tone={k.sla_compliance_rate != null && k.sla_compliance_rate >= 90 ? "green" : "red"}
              hint={`${k.sla_within} within · ${k.sla_overdue} overdue`}
            />
            <KpiCard
              label="AI Triaged"
              value={formatPercent(k.ai_triage_rate)}
              tone="blue"
              hint={`${k.ai_triaged} complaints`}
            />
            <KpiCard
              label="Escalated"
              value={formatPercent(k.escalation_rate)}
              tone="yellow"
              hint={`${k.escalated} complaints`}
            />
            <KpiCard
              label="Citizen Satisfaction"
              value={k.satisfaction_avg != null ? `${k.satisfaction_avg.toFixed(1)} / 5` : "—"}
              tone="green"
              hint={`${k.satisfaction_count} ratings`}
            />
            <KpiCard label="SLA Orders w/ Deadline" value={k.sla_orders_with_deadline.toLocaleString()} />
          </div>

          {/* Timeseries */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Complaints Over Time</CardTitle>
                <CardDescription>Total complaints per day (or month) in the selected range.</CardDescription>
              </CardHeader>
              <CardContent>
                {charts?.complaints_over_time.length ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={charts.complaints_over_time} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="period" tickFormatter={tickPeriod} tick={{ fontSize: 12 }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={32} />
                      <Tooltip labelFormatter={(label) => tickPeriod(String(label ?? ""))} />
                      <Area type="monotone" dataKey="total" name="Total" stroke={BLUE} fill={BLUE} fillOpacity={0.15} strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyOverview />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Resolution Trend</CardTitle>
                <CardDescription>Complaints created vs. resolved per period.</CardDescription>
              </CardHeader>
              <CardContent>
                {charts?.resolution_trend.length ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={charts.resolution_trend} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="period" tickFormatter={tickPeriod} tick={{ fontSize: 12 }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={32} />
                      <Tooltip labelFormatter={(label) => tickPeriod(String(label ?? ""))} />
                      <Legend />
                      <Area type="monotone" dataKey="total" name="Created" stroke={SLATE} fill={SLATE} fillOpacity={0.1} strokeWidth={2} />
                      <Area type="monotone" dataKey="resolved" name="Resolved" stroke={GREEN} fill={GREEN} fillOpacity={0.15} strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyOverview />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Category + Ward */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Complaints by Category</CardTitle>
                <CardDescription>Total vs. resolved per category with resolution rate.</CardDescription>
              </CardHeader>
              <CardContent>
                {charts?.categories.length ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={charts.categories} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="category" tickFormatter={(v) => categoryLabel(v)} tick={{ fontSize: 10 }} interval={0} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={32} />
                      <Tooltip
                        formatter={(value) => (value != null ? String(value) : value)}
                        labelFormatter={(label) => categoryLabel(String(label ?? ""))}
                      />
                      <Legend />
                      <Bar dataKey="total" name="Total" fill={BLUE} radius={[4, 4, 0, 0]} />
                      <Bar dataKey="resolved" name="Resolved" fill={GREEN} radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyOverview />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Complaints by Ward</CardTitle>
                <CardDescription>Highest-volume wards in the selected range.</CardDescription>
              </CardHeader>
              <CardContent>
                {charts?.wards.length ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart
                      data={charts.wards
                        .slice()
                        .sort((a, b) => b.total - a.total)
                        .slice(0, 12)}
                      layout="vertical"
                      margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
                      <YAxis type="category" dataKey="ward_name" width={130} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="total" name="Total" fill={VIOLET} radius={[0, 4, 4, 0]} />
                      <Bar dataKey="resolved" name="Resolved" fill={GREEN} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyOverview />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Department table + SLA */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Department Performance</CardTitle>
                <CardDescription>Work order completion and SLA outcomes by department.</CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                {charts?.departments.length ? (
                  <table className="min-w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-border-soft text-xs uppercase text-slate-400">
                        <th className="py-2 pr-4 font-medium">Department</th>
                        <th className="py-2 pr-4 font-medium">Orders</th>
                        <th className="py-2 pr-4 font-medium">Completed</th>
                        <th className="py-2 pr-4 font-medium">Avg Time</th>
                        <th className="py-2 pr-4 font-medium">SLA</th>
                      </tr>
                    </thead>
                    <tbody>
                      {charts.departments.map((d) => (
                        <tr key={d.department} className="border-b border-slate-100 last:border-0">
                          <td className="py-2 pr-4 font-medium text-slate-900">{d.department}</td>
                          <td className="py-2 pr-4">{d.total}</td>
                          <td className="py-2 pr-4">{d.completed}</td>
                          <td className="py-2 pr-4">{formatDuration(d.avg_completion_seconds)}</td>
                          <td className="py-2 pr-4">
                            <Badge
                              variant={d.compliance_rate != null && d.compliance_rate >= 90 ? "success" : "secondary"}
                            >
                              {formatPercent(d.compliance_rate)}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <EmptyOverview />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>SLA Performance by Priority</CardTitle>
                <CardDescription>Work orders completed within vs. past their deadline.</CardDescription>
              </CardHeader>
              <CardContent>
                {charts?.sla_performance.length ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={charts.sla_performance} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="priority" tickFormatter={(v) => PRIORITY_LABELS[v] ?? v} tick={{ fontSize: 11 }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={32} />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="within" name="Within SLA" stackId="sla" fill={GREEN} />
                      <Bar dataKey="overdue" name="Overdue" stackId="sla" fill={RED} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyOverview />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Satisfaction + Heatmap */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Citizen Satisfaction</CardTitle>
                <CardDescription>Distribution of 1–5 star ratings for resolved complaints.</CardDescription>
              </CardHeader>
              <CardContent>
                {k.satisfaction_distribution.length ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie
                        data={k.satisfaction_distribution}
                        dataKey="count"
                        nameKey="rating"
                        cx="50%"
                        cy="50%"
                        outerRadius={90}
                        label={(entry) =>
                          `${entry.payload?.rating ?? ""}★ · ${entry.payload?.count ?? ""}`
                        }
                      >
                        {k.satisfaction_distribution.map((bucket, index) => (
                          <Cell key={bucket.rating} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value) => (value != null ? String(value) : value)} />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyState
                    icon={<Flame className="h-8 w-8 text-slate-400" />}
                    title="No ratings yet"
                    description="Ratings appear here once citizens rate their resolved complaints."
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Complaint Heatmap</CardTitle>
                <CardDescription>
                  <span className="inline-flex items-center gap-1">
                    {heatmap?.total_points ? `${heatmap.total_points.toLocaleString()} complaints plotted` : "No plotted complaints"}
                  </span>
                </CardDescription>
              </CardHeader>
              <CardContent>
                {heatmap && heatmap.total_points > 0 ? (
                  <AnalyticsHeatmap clusters={heatmap.clusters} />
                ) : (
                  <div className="flex h-[280px] items-center justify-center">
                    <EmptyOverview />
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}