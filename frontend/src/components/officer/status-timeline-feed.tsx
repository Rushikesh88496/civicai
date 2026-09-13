"use client";

import { Activity, Radio, Wrench } from "lucide-react";
import { formatDateTime, statusLabel } from "@/components/dashboard/format";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { cn } from "@/lib/utils";
import type { ComplaintTimeline } from "@/lib/citizen-api";

// Officer-skewed human-readable labels for work-order milestones. Status
// events are labelled via STATUS_LABELS; everything here is a *work* milestone
// the officer cares about while reviewing the resolution.
const OFFICER_WORK_ACTION_LABEL: Record<string, string> = {
  APPROVE: "Officer approved the work order",
  ASSIGN: "Work order assigned",
  REASSIGN: "Reassigned to another worker",
  ESCALATE: "Escalated for urgent attention",
  REJECT: "Officer rejected the work order",
  CLOSE: "Complaint closed",
  DISPATCH: "Work order created",
  ACCEPT: "Field worker accepted the task",
  START_WORK: "Field worker started work",
  FINISH_WORK: "Field worker finished the task",
  SUBMIT_EVIDENCE: "Evidence submitted for verification",
  RESOLUTION_CONFIRMED: "Officer confirmed the resolution",
  COMPLETE_WORK: "Field worker completed the task",
  CHECK_IN: "Field worker checked in",
  PHOTO_BEFORE: "Before photo added",
  PHOTO_AFTER: "After photo added",
  NOTE_ADDED: "Field worker added notes",
  REOPEN: "Verification required follow-up",
};

function officerWorkActionLabel(action: string): string {
  return (
    OFFICER_WORK_ACTION_LABEL[action] ??
    action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

interface Item {
  key: string;
  recorded_at: string;
  status?: string;
  action?: string;
  actor?: string | null;
  note?: string | null;
}

export function StatusTimelineFeed({ timeline }: { timeline: ComplaintTimeline }) {
  const items: Item[] = [
    ...timeline.events.map((e) => ({
      key: `status-${e.id}`,
      recorded_at: e.recorded_at,
      status: e.status,
      note: e.note,
    })),
    ...timeline.work_order_events.map((e) => ({
      key: `work-${e.work_order_id}-${e.recorded_at}-${e.action}`,
      recorded_at: e.recorded_at,
      action: e.action,
      actor: e.actor_name,
      note: e.note,
    })),
  ].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );

  return (
    <div className="overflow-hidden rounded-xl border border-border-soft bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border-soft bg-slate-50/60 px-4 py-3.5 sm:px-5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
          <Activity className="h-4 w-4" />
        </span>
        <div>
          <h2 className="text-base font-semibold tracking-tight text-slate-900">
            Status Timeline
          </h2>
          <p className="text-sm text-slate-500">
            Audit log of status changes and field work milestones.
          </p>
        </div>
        <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
          {items.length} entries
        </span>
      </div>

      {items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-400">No updates yet.</p>
      ) : (
        <ol className="divide-y divide-border-soft">
          {items.map((item) => {
            const isStatus = item.status != null;
            return (
              <li
                key={item.key}
                className="flex items-start gap-3 px-4 py-3 hover:bg-slate-50/50 sm:px-5"
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                    isStatus
                      ? "bg-primary-50 text-primary-600"
                      : "bg-slate-100 text-slate-500"
                  )}
                >
                  {isStatus ? (
                    <Radio className="h-4 w-4" />
                  ) : (
                    <Wrench className="h-4 w-4" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-slate-800">
                      {isStatus
                        ? statusLabel(item.status ?? "")
                        : officerWorkActionLabel(item.action ?? "")}
                    </p>
                    {isStatus ? (
                      <StatusBadge value={item.status ?? ""} />
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                        Work milestone
                      </span>
                    )}
                  </div>
                  {item.actor && (
                    <p className="mt-0.5 text-xs text-slate-400">
                      By <span className="font-medium text-slate-500">{item.actor}</span>
                    </p>
                  )}
                  {item.note && (
                    <p className="mt-1 rounded-md border-l-2 border-slate-200 bg-slate-50/60 px-2 py-1 text-sm leading-relaxed text-slate-600">
                      <span className="font-semibold text-slate-400">Note:</span>{" "}
                      {item.note}
                    </p>
                  )}
                </div>
                <time className="shrink-0 pt-0.5 text-xs text-slate-400">
                  {formatDateTime(item.recorded_at)}
                </time>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}