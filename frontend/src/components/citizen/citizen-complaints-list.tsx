"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, ClipboardList, Search, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Pagination } from "@/components/ui/pagination";
import { Progress } from "@/components/ui/progress";
import { StatusBadge, PriorityBadge, CategoryBadge } from "@/components/dashboard/status-badge";
import { formatDate, timeAgo, statusLabel } from "@/components/dashboard/format";
import {
  complaintProgress,
  complaintStageLabel,
  complaintStageTone,
} from "@/lib/complaint-stage";
import type { Complaint, ComplaintPriority } from "@/lib/citizen-api";

const PAGE_SIZE = 6;

const STATUS_OPTIONS: string[] = [
  "SUBMITTED",
  "AI_ANALYZING",
  "EVIDENCE_VERIFIED",
  "WARD_IDENTIFIED",
  "PRIORITIZED",
  "DEPARTMENT_ASSIGNED",
  "WORK_ORDER_CREATED",
  "WORKER_ASSIGNED",
  "IN_PROGRESS",
  "WORK_COMPLETED",
  "EVIDENCE_SUBMITTED",
  "CITIZEN_VERIFIED",
  "RESOLVED",
  "CLOSED",
  "OPEN",
  "ESCALATED",
];

const PRIORITY_OPTIONS: ComplaintPriority[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

interface CitizenComplaintsListProps {
  complaints: Complaint[];
  loading: boolean;
}

export function CitizenComplaintsList({ complaints, loading }: CitizenComplaintsListProps) {
  const [query, setQuery] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState("ALL");
  const [priorityFilter, setPriorityFilter] = React.useState("ALL");
  const [page, setPage] = React.useState(1);

  const hasFilters = query.trim().length > 0 || statusFilter !== "ALL" || priorityFilter !== "ALL";

  const filtered = React.useMemo(() => {
    let rows = complaints;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      rows = rows.filter(
        (c) =>
          c.title.toLowerCase().includes(q) ||
          (c.category || "").toLowerCase().includes(q) ||
          (c.location || "").toLowerCase().includes(q)
      );
    }
    if (statusFilter !== "ALL") rows = rows.filter((c) => c.status === statusFilter);
    if (priorityFilter !== "ALL") rows = rows.filter((c) => c.priority === priorityFilter);
    return rows;
  }, [complaints, query, statusFilter, priorityFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedRows = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const clearFilters = () => {
    setQuery("");
    setStatusFilter("ALL");
    setPriorityFilter("ALL");
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto_auto]">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            className="pl-9"
            placeholder="Search title, location…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            aria-label="Search complaints"
          />
        </div>
        <Select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by status"
        >
          <option value="ALL">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </Select>
        <Select
          value={priorityFilter}
          onChange={(e) => {
            setPriorityFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by priority"
        >
          <option value="ALL">All priorities</option>
          {PRIORITY_OPTIONS.map((p) => (
            <option key={p} value={p}>
              {p.charAt(0) + p.slice(1).toLowerCase()}
            </option>
          ))}
        </Select>
      </div>

      {!loading && hasFilters && (
        <div className="flex items-center justify-between text-sm text-slate-500">
          <span>
            {filtered.length} {filtered.length === 1 ? "match" : "matches"}
          </span>
          <Button variant="ghost" size="sm" className="gap-1 text-slate-500" onClick={clearFilters}>
            <X className="h-3.5 w-3.5" />
            Clear filters
          </Button>
        </div>
      )}

      <Card>
        <CardContent className="p-4 sm:p-5">
          {loading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-[116px] w-full rounded-2xl" />
              ))}
            </div>
          ) : complaints.length === 0 ? (
            <EmptyState
              icon={<ClipboardList className="h-8 w-8 text-slate-300" />}
              title="You haven't reported anything yet"
              description="No civic issues have been submitted from your account. Report the first one so the municipality can take action."
              action={
                <Link href="/report">
                  <Button className="gap-2">
                    <ClipboardList className="h-4 w-4" />
                    Report your first issue
                  </Button>
                </Link>
              }
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Search className="h-8 w-8 text-slate-300" />}
              title="No complaints match your filters"
              description="Try a different keyword, status or priority."
              action={
                <Button variant="outline" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <ul className="divide-y divide-border-soft">
              {pagedRows.map((c) => {
                const progress = complaintProgress(c.status);
                const tone = complaintStageTone(c.status);
                return (
                  <li key={c.id} className="first:pt-0 last:pb-0 [&:not(:first-child)]:pt-3 [&:not(:last-child)]:pb-3">
                    <Link
                      href={`/dashboard/complaints/${c.id}`}
                      className="group flex items-start gap-3 rounded-2xl p-3 transition-colors hover:bg-slate-50 sm:items-center sm:p-4"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-semibold text-slate-900 group-hover:text-primary-700 sm:text-[15px]">
                            {c.title}
                          </span>
                          <StatusBadge value={c.status} />
                        </div>

                        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <CategoryBadge value={c.category} />
                          <PriorityBadge value={c.priority} />
                          <span className="hidden items-center sm:inline-flex">
                            <span aria-hidden="true">·</span>
                            <span className="ml-2">{c.location || "Location pending"}</span>
                          </span>
                        </div>

                        <div className="mt-2.5 flex items-center gap-3">
                          <Progress value={progress} tone={tone} className="h-1.5 max-w-[180px]" />
                          <span className="whitespace-nowrap text-[11px] font-medium text-slate-500">
                            {complaintStageLabel(c.status)}
                          </span>
                        </div>

                        <p className="mt-2 text-xs text-slate-400">
                          Reported {formatDate(c.created_at)} · {timeAgo(c.created_at)}
                        </p>
                      </div>
                      <ChevronRight className="mt-1 h-5 w-5 shrink-0 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-primary-500 sm:mt-0" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {!loading && filtered.length > PAGE_SIZE && (
        <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={setPage} />
      )}
    </div>
  );
}