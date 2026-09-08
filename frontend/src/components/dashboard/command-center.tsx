"use client";

import * as React from "react";
import {
  RefreshCw,
  ListOrdered,
  Inbox,
  Search,
  MapPin,
  Radar,
  Sparkles,
  Flame,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { formatDate, formatDateTime, categoryLabel, statusLabel } from "@/components/dashboard/format";
import { CommandCenterMap } from "@/components/dashboard/command-center-map";
import { SlaMonitor } from "@/components/officer/sla-monitor";
import {
  fetchCommandCenterKpis,
  fetchCommandCenterQueue,
  fetchCommandCenterMap,
  fetchCommandCenterAiActivity,
  type CommandCenterKpis,
  type CommandCenterQueue,
  type CommandCenterMap as MapData,
  type AiActivity,
  type CommandCenterComplaint,
} from "@/lib/officer-api";

const PRIORITY_LABELS: Record<string, string> = {
  P1_CRITICAL: "P1 Critical",
  P2_HIGH: "P2 High",
  P3_MEDIUM: "P3 Medium",
  P4_LOW: "P4 Low",
};

const AGENT_LABELS: Record<string, string> = {
  triage: "Triage",
  vision: "Vision",
  correlation: "Duplicate Check",
  context: "Context",
  priority: "Priority Score",
  routing: "Routing",
  dispatch: "Dispatch",
  gis: "GIS",
  sla_monitor: "SLA Monitor",
};

const STATUS_OPTIONS = [
  "OPEN",
  "SUBMITTED",
  "AI_ANALYZING",
  "EVIDENCE_VERIFIED",
  "WARD_IDENTIFIED",
  "PRIORITIZED",
  "DEPARTMENT_ASSIGNED",
  "WORK_ORDER_CREATED",
  "WORKER_ASSIGNED",
  "IN_PROGRESS",
  "CITIZEN_VERIFIED",
  "ESCALATED",
  "RESOLVED",
  "CLOSED",
];

const AI_STATUSES = new Set([
  "AI_ANALYZING",
  "EVIDENCE_VERIFIED",
  "WARD_IDENTIFIED",
  "PRIORITIZED",
]);

function priorityBadge(priority?: string | null) {
  if (!priority) return null;
  const variant =
    priority === "P1_CRITICAL"
      ? "destructive"
      : priority === "P2_HIGH"
        ? "warning"
        : priority === "P3_MEDIUM"
          ? "secondary"
          : "success";
  return <Badge variant={variant}>{PRIORITY_LABELS[priority] ?? priority}</Badge>;
}

function statusBadge(status: string) {
  const lower = status.toLowerCase();
  if (AI_STATUSES.has(status)) return <Badge variant="ai">{statusLabel(status)}</Badge>;
  const variant =
    lower.includes("resolved") || lower.includes("closed") || lower.includes("citizen_verified")
      ? "success"
      : lower.includes("escalated")
        ? "destructive"
        : lower.includes("open") || lower.includes("submitted")
          ? "warning"
          : "secondary";
  return <Badge variant={variant}>{statusLabel(status)}</Badge>;
}

type Tone = "primary" | "danger" | "warning" | "info" | "success" | "slate";

const TONE_ICON: Record<Tone, string> = {
  primary: "text-primary-600 bg-primary-50",
  danger: "text-danger-600 bg-danger-50",
  warning: "text-warning-600 bg-warning-50",
  info: "text-info-600 bg-info-50",
  success: "text-success-600 bg-success-50",
  slate: "text-slate-600 bg-slate-100",
};

const TONE_VALUE: Record<Tone, string> = {
  primary: "text-primary-700",
  danger: "text-danger-600",
  warning: "text-warning-700",
  info: "text-info-700",
  success: "text-success-700",
  slate: "text-slate-900",
};

function KpiCard({
  label,
  value,
  icon,
  tone = "slate",
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <Card className="p-4 transition-shadow hover:shadow-card-hover">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-slate-500">{label}</span>
        <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", TONE_ICON[tone])}>
          {icon}
        </span>
      </div>
      <div className={cn("mt-3 text-2xl font-semibold tabular-nums tracking-tight", TONE_VALUE[tone])}>
        {value}
      </div>
    </Card>
  );
}

const defaultKpis: CommandCenterKpis = {
  total_complaints: 0,
  p1: 0,
  p2: 0,
  p3: 0,
  p4: 0,
  pending: 0,
  in_progress: 0,
  resolved: 0,
  sla_breaches: 0,
  sla_at_risk: 0,
};

export function CommandCenter() {
  const [kpis, setKpis] = React.useState<CommandCenterKpis>(defaultKpis);
  const [queue, setQueue] = React.useState<CommandCenterQueue | null>(null);
  const [mapData, setMapData] = React.useState<MapData | null>(null);
  const [activity, setActivity] = React.useState<AiActivity | null>(null);

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [tick, setTick] = React.useState(0);

  // Queue filter state
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [priority, setPriority] = React.useState("");
  const [department, setDepartment] = React.useState("");
  const [page, setPage] = React.useState(1);

  const pageSize = 10;

  React.useEffect(() => {
    let active = true;
    Promise.all([
      fetchCommandCenterKpis(),
      fetchCommandCenterQueue({
        page,
        page_size: pageSize,
        status: status || undefined,
        priority: priority || undefined,
        department: department || undefined,
        search: search || undefined,
      }),
      fetchCommandCenterMap(),
      fetchCommandCenterAiActivity(),
    ])
      .then(([k, q, m, a]) => {
        if (!active) return;
        setError(null);
        setKpis(k);
        setQueue(q);
        setMapData(m);
        setActivity(a);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load command center.");
      })
      .finally(() => {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => {
      active = false;
    };
  }, [tick, page, status, priority, department, search]);

  // Light poll fallback (Redis may be down; realtime degrades to this).
  React.useEffect(() => {
    const id = setInterval(() => {
      setTick((t) => t + 1);
    }, 30000);
    return () => clearInterval(id);
  }, []);

  const reload = React.useCallback(() => {
    setRefreshing(true);
    setTick((t) => t + 1);
  }, []);

  if (loading) return <LoadingState message="Loading command center…" />;

  if (error) {
    return (
      <ErrorState
        title="Unable to load command center"
        description={error}
        action={
          <Button variant="outline" onClick={reload}>
            Retry
          </Button>
        }
      />
    );
  }

  const totalPages = queue?.total_pages ?? 1;
  const hotspots = (mapData?.hotspots ?? []).slice().sort((a, b) => b.priority_weight - a.priority_weight);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Command Center
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Real-time civic complaints, priority queue, and AI agent activity.
          </p>
        </div>
        <Button variant="outline" onClick={reload} disabled={refreshing}>
          <RefreshCw className={cn("mr-2 h-4 w-4", refreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Total Complaints" value={kpis.total_complaints} tone="primary" icon={<ListOrdered className="h-4 w-4" />} />
        <KpiCard label="P1 Critical" value={kpis.p1} tone="danger" icon={<Flame className="h-4 w-4" />} />
        <KpiCard label="P2 High" value={kpis.p2} tone="warning" icon={<Flame className="h-4 w-4" />} />
        <KpiCard label="P3 Medium" value={kpis.p3} tone="info" icon={<ListOrdered className="h-4 w-4" />} />
        <KpiCard label="P4 Low" value={kpis.p4} tone="slate" icon={<ListOrdered className="h-4 w-4" />} />
        <KpiCard label="Pending" value={kpis.pending} icon={<Inbox className="h-4 w-4" />} />
        <KpiCard label="In Progress" value={kpis.in_progress} tone="warning" icon={<RefreshCw className="h-4 w-4" />} />
        <KpiCard label="Resolved" value={kpis.resolved} tone="success" icon={<Sparkles className="h-4 w-4" />} />
        <KpiCard
          label="SLA Breaches"
          value={kpis.sla_breaches}
          tone={kpis.sla_breaches > 0 ? "danger" : "success"}
          icon={<Flame className="h-4 w-4" />}
        />
        <KpiCard
          label="SLA At Risk"
          value={kpis.sla_at_risk}
          tone={kpis.sla_at_risk > 0 ? "warning" : "success"}
          icon={<RefreshCw className="h-4 w-4" />}
        />
      </div>

      {/* Queue + map row */}
      <div className="grid gap-6 lg:grid-cols-5">
        {/* Priority queue */}
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListOrdered className="h-5 w-5 text-primary-600" />
              Priority Queue
            </CardTitle>
            <CardDescription>Filter, search, and review complaints assigned to your command.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Filters */}
            <div className="flex flex-wrap gap-2">
              <div className="relative min-w-[180px] flex-1">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
                <Input
                  className="pl-8"
                  placeholder="Search title or ID…"
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                />
              </div>
              <Select className="w-36" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
                <option value="">All Status</option>
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>{statusLabel(s)}</option>
                ))}
              </Select>
              <Select className="w-36" value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1); }}>
                <option value="">All Priority</option>
                <option value="P1_CRITICAL">P1 Critical</option>
                <option value="P2_HIGH">P2 High</option>
                <option value="P3_MEDIUM">P3 Medium</option>
                <option value="P4_LOW">P4 Low</option>
              </Select>
              <Select className="w-40" value={department} onChange={(e) => { setDepartment(e.target.value); setPage(1); }}>
                <option value="">All Departments</option>
                {(mapData?.work_orders ?? [])
                  .map((wo) => wo.department)
                  .filter((d, i, arr) => d && arr.indexOf(d) === i)
                  .map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
              </Select>
            </div>

            {/* Rows */}
            <div className="space-y-2.5">
              {(queue?.items ?? []).map((c) => (
                <QueueRow key={c.id} complaint={c} />
              ))}
              {(!queue || queue.items.length === 0) && (
                <EmptyState
                  icon={<Inbox className="h-8 w-8 text-slate-300" />}
                  title="No complaints found"
                  description="Try adjusting your filters or search query."
                />
              )}
            </div>

            <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
          </CardContent>
        </Card>

        {/* Map + hotspots */}
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MapPin className="h-5 w-5 text-primary-600" />
                Incident Map
              </CardTitle>
              <CardDescription>Citizen-complaint locations across the city.</CardDescription>
            </CardHeader>
            <CardContent>
              {mapData ? (
                <CommandCenterMap data={mapData} />
              ) : (
                <div className="h-96 w-full bg-slate-100" />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Radar className="h-5 w-5 text-danger-600" />
                Hotspot Wards
              </CardTitle>
              <CardDescription>Wards ranked by priority-weighted open complaints.</CardDescription>
            </CardHeader>
            <CardContent>
              {hotspots.length === 0 ? (
                <p className="text-sm text-slate-500">No hotspot data available.</p>
              ) : (
                <ul className="space-y-2.5">
                  {hotspots.slice(0, 8).map((h) => (
                    <li key={h.ward_code ?? h.ward_name ?? "h"} className="flex items-center justify-between gap-3 text-sm">
                      <span className="min-w-0 truncate font-medium text-slate-800">{h.ward_name ?? h.ward_code ?? "Ward"}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="text-slate-500">{h.open_count} open</span>
                        <Badge variant={h.priority_weight >= 5 ? "destructive" : h.priority_weight >= 2.5 ? "warning" : "secondary"}>
                          {Math.round(h.priority_weight * 10) / 10}
                        </Badge>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* AI activity */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-ai-600" />
            AI Agent Activity
          </CardTitle>
          <CardDescription>
            Auto-triage, vision, duplicate, context, priority, routing, dispatch, and SLA agents.
            {activity?.last_updated ? ` Last updated ${formatDateTime(activity.last_updated)}.` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {(activity?.agents ?? []).length === 0 ? (
            <p className="text-sm text-slate-500">No agent activity recorded yet.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {activity!.agents.map((ag) => (
                <AgentCard key={ag.agent} agent={ag} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* SLA Monitoring */}
      <SlaMonitor />
    </div>
  );
}

function QueueRow({ complaint }: { complaint: CommandCenterComplaint }) {
  return (
    <div className="rounded-lg border border-border-soft p-3 transition-colors hover:border-border-strong hover:bg-slate-50/60">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-slate-900">{complaint.title}</p>
            {priorityBadge(complaint.priority ?? complaint.complaint_priority)}
            {statusBadge(complaint.status)}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {complaint.complaint_id} · {categoryLabel(complaint.category)}
            {complaint.department ? ` · ${complaint.department}` : ""}
            {complaint.ward_name ? ` · ${complaint.ward_name}` : ""}
            {complaint.sla_due_at ? ` · SLA due ${formatDate(complaint.sla_due_at)}` : ""}
          </p>
        </div>
        <span className="whitespace-nowrap text-xs text-slate-400">{formatDate(complaint.created_at)}</span>
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: NonNullable<AiActivity>["agents"][number] }) {
  const label = AGENT_LABELS[agent.agent] ?? agent.agent;
  return (
    <div className={cn("rounded-lg border p-3", agent.enabled ? "border-border-soft bg-surface" : "border-dashed border-border-strong bg-slate-50/50")}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
          <Sparkles className="h-3.5 w-3.5 text-ai-500" />
          {label}
        </span>
        {!agent.enabled && <Badge variant="outline">off</Badge>}
      </div>
      <div className="mt-1 text-xs text-slate-500">
        {agent.enabled ? `${agent.total} runs · ${agent.failed} failed` : "Agent not active"}
      </div>
      <div className="mt-2 flex h-1.5 w-full gap-0.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full bg-danger-400"
          style={{ width: `${agent.total ? (agent.failed / agent.total) * 100 : 0}%` }}
          title={`${agent.failed} failed`}
        />
        <div
          className="h-full bg-success-400"
          style={{ width: `${agent.total ? (agent.completed / agent.total) * 100 : 0}%` }}
          title={`${agent.completed} completed`}
        />
        <div
          className="h-full bg-primary-400"
          style={{ width: `${agent.total ? (agent.running / agent.total) * 100 : 0}%` }}
          title={`${agent.running} running`}
        />
        <div
          className="h-full bg-slate-300"
          style={{ width: `${agent.total ? (agent.pending / agent.total) * 100 : 0}%` }}
          title={`${agent.pending} pending`}
        />
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
        <span>P {agent.pending}</span>
        <span>R {agent.running}</span>
        <span>C {agent.completed}</span>
        <span>F {agent.failed}</span>
      </div>
    </div>
  );
}