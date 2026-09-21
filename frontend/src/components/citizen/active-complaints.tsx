"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, ChevronRight, ClipboardList, HelpCircle } from "lucide-react";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { StatusBadge, PriorityBadge } from "@/components/dashboard/status-badge";
import { categoryLabel } from "@/components/dashboard/format";
import {
  complaintProgress,
  complaintStageLabel,
  complaintStageTone,
  isClosedStatus,
} from "@/lib/complaint-stage";
import { findCategory } from "@/lib/complaint-categories";
import type { Complaint } from "@/lib/citizen-api";

interface ActiveComplaintsProps {
  complaints: Complaint[];
  loading: boolean;
  limit?: number;
}

function ComplaintRow({ complaint }: { complaint: Complaint }) {
  const CategoryIcon = findCategory(complaint.category)?.icon ?? HelpCircle;
  const progress = complaintProgress(complaint.status);
  const tone = complaintStageTone(complaint.status);

  return (
    <li>
      <Link
        href={`/dashboard/complaints/${complaint.id}`}
        className="group flex items-center gap-3 rounded-2xl border border-border-soft bg-surface p-4 shadow-card transition-all hover:-translate-y-0.5 hover:border-primary-200 hover:shadow-card-hover sm:gap-4 sm:p-5"
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
          <CategoryIcon className="h-5 w-5" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-slate-900 group-hover:text-primary-700 sm:text-[15px]">
              {complaint.title}
            </span>
            <span className="hidden md:inline-flex">
              <PriorityBadge value={complaint.priority} />
            </span>
          </div>

          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
            <span className="font-medium text-slate-600">{categoryLabel(complaint.category)}</span>
            <span aria-hidden="true">·</span>
            <span>{complaint.location || "Location pending"}</span>
          </div>

          <div className="mt-2.5 flex items-center gap-3">
            <Progress value={progress} tone={tone} className="h-1.5 max-w-[180px]" />
            <span className="whitespace-nowrap text-[11px] font-medium text-slate-500">
              {complaintStageLabel(complaint.status)} · {progress}%
            </span>
          </div>
        </div>

        <div className="hidden shrink-0 sm:block">
          <StatusBadge value={complaint.status} />
        </div>
        <ChevronRight className="h-5 w-5 shrink-0 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-primary-500" />
      </Link>
    </li>
  );
}

export function ActiveComplaints({ complaints, loading, limit = 4 }: ActiveComplaintsProps) {
  const active = complaints.filter((c) => !isClosedStatus(c.status));
  const visible = active.slice(0, limit);

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      aria-label="Active complaints"
    >
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <ClipboardList className="h-5 w-5 text-primary-600" />
              Active complaints
            </CardTitle>
            <p className="mt-1 text-sm text-slate-500">
              {loading
                ? "Loading your latest reports…"
                : active.length === 0
                  ? "Nothing in progress right now."
                  : `Showing your ${visible.length} most recent ${visible.length === 1 ? "report" : "reports"}.`}
            </p>
          </div>
          <Link
            href="/dashboard/complaints"
            className="hidden shrink-0 items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700 sm:inline-flex"
          >
            View all
            <ArrowRight className="h-4 w-4" />
          </Link>
        </CardHeader>

        <CardContent className="pt-3">
          {loading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-[92px] w-full rounded-2xl" />
              ))}
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              icon={<ClipboardList className="h-8 w-8 text-slate-300" />}
              title="No active complaints"
              description="You have no open civic reports right now. If you notice an issue in your area, let the municipality know."
              action={
                <Link href="/report">
                  <Button className="gap-2">
                    <HelpCircle className="h-4 w-4" />
                    Report your first issue
                  </Button>
                </Link>
              }
            />
          ) : (
            <ul className="space-y-3">
              {visible.map((c) => (
                <ComplaintRow key={c.id} complaint={c} />
              ))}
            </ul>
          )}
        </CardContent>

        {!loading && visible.length > 0 && (
          <CardFooter className="pt-1 sm:hidden">
            <Link href="/dashboard/complaints" className="w-full">
              <Button variant="outline" className="w-full gap-2">
                View all complaints
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </CardFooter>
        )}
      </Card>
    </motion.section>
  );
}