"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  TimerReset,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { formatDateTime } from "@/components/dashboard/format";
import {
  useSlaInsights,
  type SlaHealth,
  type SlaInsights,
} from "@/components/officer/sla-insights";

const HEALTH_META: Record<
  SlaHealth,
  { label: string; tone: "success" | "warning" | "danger"; className: string }
> = {
  ON_TRACK: {
    label: "On Track",
    tone: "success",
    className: "bg-success-50 text-success-700",
  },
  AT_RISK: {
    label: "At Risk",
    tone: "warning",
    className: "bg-warning-50 text-warning-800",
  },
  OVERDUE: {
    label: "Overdue",
    tone: "danger",
    className: "bg-danger-50 text-danger-700",
  },
  COMPLETED: {
    label: "Completed",
    tone: "success",
    className: "bg-success-50 text-success-700",
  },
};

function fmtCountdown(ms: number): string {
  const total = Math.abs(Math.round(ms / 60000));
  const d = Math.floor(total / 1440);
  const h = Math.floor((total % 1440) / 60);
  const m = total % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${Math.max(1, m)}m`;
}

export function SlaStatusCard({
  complaintId,
  insights,
}: {
  complaintId: string;
  insights?: SlaInsights;
}) {
  const own = useSlaInsights(complaintId, insights ? false : true);
  const { loading, order, health, remainingMs, elapsedPct } =
    insights ?? own;

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-0">
          <CardTitle className="flex items-center gap-2 text-sm">
            <TimerReset className="h-4 w-4 text-primary-500" /> SLA
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-3 w-20" />
        </CardContent>
      </Card>
    );
  }

  if (!health || !order) return null;

  const meta = HEALTH_META[health];

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <TimerReset className="h-4 w-4 text-primary-500" /> SLA
          </CardTitle>
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.className}`}
          >
            {health === "OVERDUE" || health === "AT_RISK" ? (
              <AlertTriangle className="h-3 w-3" />
            ) : (
              <CheckCircle2 className="h-3 w-3" />
            )}
            {meta.label}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Progress value={elapsedPct} max={100} tone={meta.tone} />
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {health === "OVERDUE"
              ? `Overdue by ${fmtCountdown(-remainingMs)}`
              : health === "COMPLETED"
                ? "Deadline met"
                : `Time left ${fmtCountdown(remainingMs)}`}
          </span>
          <span className="text-slate-400">
            due {formatDateTime(order.due_at as string)}
          </span>
        </div>
        {order.sla_hours != null && (
          <p className="text-[11px] text-slate-400">
            {order.status === "APPROVED" || order.status === "ASSIGNED"
              ? "Clock runs from work-order approval."
              : `Work order ${order.status.replace(/_/g, " ").toLowerCase()} — ${order.sla_hours}h SLA window.`}
          </p>
        )}
      </CardContent>
    </Card>
  );
}