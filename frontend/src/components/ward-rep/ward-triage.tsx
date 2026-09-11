"use client";

import * as React from "react";
import Link from "next/link";
import {
  RefreshCw,
  ListOrdered,
  Inbox,
  Search,
  BrainCircuit,
  Flame,
  CheckCircle2,
  Timer,
} from "lucide-react";
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
import { fetchCommandCenterKpis, fetchCommandCenterQueue, type CommandCenterKpis, type CommandCenterQueue, type CommandCenterComplaint } from "@/lib/officer-api";
import { fetchWardDashboard, type WardDashboard } from "@/lib/ward-rep-api";

const PRIORITY_LABELS: Record<string, string> = {
  P1_CRITICAL: "P1 Critical",
  P2_HIGH: "P2 High",
  P3_MEDIUM: "P3 Medium",
  P4_LOW: "P4 Low",
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

function KpiCard({
  label,
  value,
  icon,
  toneClass,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  toneClass: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-slate-500">{label}</span>
        <span
          className={
            `flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${toneClass}`
          }
        >
          {icon}
        </span>
      </div>
      <div className="mt-3 text-2xl font-semibold tabular-nums tracking-tight text-slate-900">
        {value}
      </div>
    </Card>
  );
}

export function WardTriage() {
  const [dashboard, setDashboard] = React.useState<WardDashboard | null>(null);
  const [kpis, setKpis] = React.useState<CommandCenterKpis | null>(null);
  const [queue, setQueue] = React.useState<CommandCenterQueue | null>(null);

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [tick, setTick] = React.useState(0);

  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [priority, setPriority] = React.useState("");
  const [page, setPage] = React.useState(1);

  const pageSize = 10;
  const hasFilters = Boolean(search || status || priority);

  React.useEffect(() => {
    let active = true;
    Promise.all([
      fetchWardDashboard(),
      fetchCommandCenterKpis(),
      fetchCommandCenterQueue({
        page,
        page_size: pageSize,
        status: status || undefined,
        priority: priority || undefined,
        search: search || undefined,
      }),
    ])
      .then(([d, k, q]) => {
        if (!active) return;
        setError(null);
        setDashboard(d);
        setKpis(k);
        setQueue(q);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load ward triage.");
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
  }, [tick, page, status, priority, search]);

  const reload = React.useCallback(() => {
    setRefreshing(true);
    setTick((t) => t + 1);
  }, []);

  if (loading) return <LoadingState message="Loading ward triage…" />;

  if (error) {
    return (
      <ErrorState
        title="Unable to load ward triage"
        description={error}
        action={
          <Button variant="outline" onClick={reload}>
            Retry
          </Button>
        }
      />
    );
  }

  const ward = dashboard?.ward;
  const k = kpis;
  const items = queue?.items ?? [];
  const totalPages = queue?.total_pages ?? 1;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            AI Triage
          </h1>
          <p className="text-sm text-slate-500">
            {ward
              ? `Complaints in Ward ${ward.code} · ${ward.name}`
              : "Your ward's complaints"}
            {" — review and take action on every filed report."}
          </p>
        </div>
        <Button variant="outline" onClick={reload} disabled={refreshing}>
          <RefreshCw className={refreshing ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
          Refresh
        </Button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Total Complaints" value={k?.total_complaints ?? 0} icon={<ListOrdered className="h-4 w-4 text-primary-600" />} toneClass="bg-primary-50" />
        <KpiCard label="P1 Critical" value={k?.p1 ?? 0} icon={<Flame className="h-4 w-4 text-danger-600" />} toneClass="bg-danger-50" />
        <KpiCard label="P2 High" value={k?.p2 ?? 0} icon={<Flame className="h-4 w-4 text-warning-600" />} toneClass="bg-warning-50" />
        <KpiCard label="Resolved" value={k?.resolved ?? 0} icon={<CheckCircle2 className="h-4 w-4 text-success-600" />} toneClass="bg-success-50" />
        <KpiCard label="SLA Breaches" value={k?.sla_breaches ?? 0} icon={<Timer className="h-4 w-4 text-danger-600" />} toneClass="bg-danger-50" />
      </div>

      {/* Priority queue */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-ai-600" />
            Ward Complaint Queue
          </CardTitle>
          <CardDescription>
            Filter, search, and open complaints assigned to your ward.
          </CardDescription>
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
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
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
          </div>

          {/* Rows */}
          <div className="space-y-2.5">
            {items.map((c) => (
              <TriageRow key={c.id} complaint={c} />
            ))}
            {items.length === 0 && (
              <EmptyState
                icon={<Inbox className="h-8 w-8 text-slate-300" />}
                title={hasFilters ? "No complaints match your filters" : "No complaints in your ward yet"}
                description={
                  hasFilters
                    ? "Try adjusting your filters or search query."
                    : "When citizens in your ward file reports, they will appear here for triage."
                }
              />
            )}
          </div>

          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        </CardContent>
      </Card>
    </div>
  );
}

function TriageRow({ complaint }: { complaint: CommandCenterComplaint }) {
  return (
    <Link
      href={`/officer/complaints/${complaint.complaint_id}`}
      className="block"
    >
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
          <span className="whitespace-nowrap text-xs text-slate-400">{formatDateTime(complaint.created_at)}</span>
        </div>
      </div>
    </Link>
  );
}