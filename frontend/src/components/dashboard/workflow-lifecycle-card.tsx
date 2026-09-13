"use client";

import { Fragment } from "react";
import {
  Check,
  Circle,
  GitBranch,
  Loader2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ComplaintTimeline } from "@/lib/citizen-api";

interface Props {
  timeline: ComplaintTimeline | null;
}

interface Stage {
  key: string;
  label: string;
  hint: string;
  matched: (summary: StageSummary) => boolean;
}

interface StageSummary {
  complaintStatuses: Set<string>;
  workActions: Set<string>;
  workStatuses: Set<string>;
}

interface StageMatch extends Stage {
  done: boolean;
  failed: boolean;
  at: string | null;
  actor: string | null;
}

/**
 * Full human-in-the-loop work lifecycle for a complaint — derived strictly
 * from the backend status trail and work-order milestone trail:
 *
 *   submitted → triaged → routed → officer review → officer approved →
 *   worker assigned → in progress → evidence → AI verified → resolution
 *   approved → resolved → closed
 *
 * An AI recommendation is deliberately NOT shown as an "assignment": only an
 * officer-approved (signed) work order is an official assignment.
 */
const STAGES: Stage[] = [
  {
    key: "SUBMITTED",
    label: "Submitted",
    hint: "Complaint reported to the civic authority.",
    matched: (s) => s.complaintStatuses.size > 0,
  },
  {
    key: "TRIAGED",
    label: "AI Triaged",
    hint: "AI assessed severity, urgency and infrastructure type.",
    matched: (s) =>
      ["PRIORITIZED", "OPEN", "IN_REVIEW", "DEPARTMENT_ASSIGNED"].some((st) =>
        s.complaintStatuses.has(st)
      ),
  },
  {
    key: "ROUTED",
    label: "Routed",
    hint: "The department responsible for the issue was decided.",
    matched: (s) =>
      s.complaintStatuses.has("DEPARTMENT_ASSIGNED") ||
      s.workActions.has("DISPATCH"),
  },
  {
    key: "OFFICER_REVIEW",
    label: "Officer Review",
    hint: "Draft work order awaiting an officer's decision.",
    matched: (s) =>
      s.workActions.has("DISPATCH") || s.workStatuses.has("PENDING_APPROVAL"),
  },
  {
    key: "SIGNED",
    label: "Officer Approved",
    hint: "Officer approved the work order — the assignment is official.",
    matched: (s) =>
      ["APPROVE", "ASSIGN", "REASSIGN"].some((a) => s.workActions.has(a)),
  },
  {
    key: "ACCEPTED",
    label: "Worker Assigned",
    hint: "Field worker accepted the assignment.",
    matched: (s) => s.workActions.has("ACCEPT"),
  },
  {
    key: "IN_PROGRESS",
    label: "In Progress",
    hint: "Work commenced at the site.",
    matched: (s) =>
      s.workActions.has("START_WORK") || s.workActions.has("FINISH_WORK") ||
      s.complaintStatuses.has("IN_PROGRESS"),
  },
  {
    key: "EVIDENCE",
    label: "Evidence Submitted",
    hint: "Before/after photos and notes logged by the worker.",
    matched: (s) =>
      ["PHOTO_BEFORE", "PHOTO_AFTER", "NOTE_ADDED", "CHECK_IN", "SUBMIT_EVIDENCE"].some(
        (a) => s.workActions.has(a)
      ),
  },
  {
    key: "AI_VERIFY",
    label: "AI Verified",
    hint: "Repair evidence passed the automated verification pass.",
    matched: (s) =>
      s.workActions.has("COMPLETE_WORK") ||
      s.workActions.has("RESOLUTION_CONFIRMED") ||
      s.complaintStatuses.has("RESOLVED") ||
      s.complaintStatuses.has("EVIDENCE_VERIFIED"),
  },
  {
    key: "OFFICER_VERIFY",
    label: "Resolution Approved",
    hint: "Officer signed off on the completed work.",
    matched: (s) =>
      s.complaintStatuses.has("RESOLVED") ||
      s.workActions.has("RESOLUTION_CONFIRMED"),
  },
  {
    key: "RESOLVED",
    label: "Resolved",
    hint: "The issue is marked resolved.",
    matched: (s) => s.complaintStatuses.has("RESOLVED"),
  },
  {
    key: "CLOSED",
    label: "Closed",
    hint: "Complaint formally closed.",
    matched: (s) =>
      s.complaintStatuses.has("CLOSED") || s.workActions.has("CLOSE"),
  },
];

function buildStages(timeline: ComplaintTimeline): StageMatch[] {
  const complaintStatuses = new Set(timeline.events.map((e) => e.status));
  const workActions = new Set(
    timeline.work_order_events.map((e) => e.action)
  );
  const workStatuses = new Set(
    timeline.work_order_events.map((e) => e.status)
  );
  const summary: StageSummary = { complaintStatuses, workActions, workStatuses };

  const all = [
    ...timeline.events.map((e) => ({
      action: e.status,
      recorded_at: e.recorded_at,
      actor_name: null,
    })),
    ...timeline.work_order_events.map((e) => ({
      action: e.action,
      recorded_at: e.recorded_at,
      actor_name: e.actor_name,
    })),
  ].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );

  const failedKeys = new Set<string>();
  if (workActions.has("REJECT")) failedKeys.add("OFFICER_REVIEW");
  if (workActions.has("REOPEN")) failedKeys.add("OFFICER_VERIFY");

  return STAGES.map((stage) => {
    const done = stage.matched(summary);
    const event = done
      ? [...all].reverse().find((e) => {
          if (stage.key === "SIGNED") {
            return ["APPROVE", "ASSIGN", "REASSIGN"].includes(e.action);
          }
          if (stage.key === "EVIDENCE") {
            return ["PHOTO_BEFORE", "PHOTO_AFTER", "NOTE_ADDED", "CHECK_IN", "SUBMIT_EVIDENCE"].includes(
              e.action
            );
          }
          if (stage.key === "AI_VERIFY") {
            return ["COMPLETE_WORK", "RESOLUTION_CONFIRMED"].includes(e.action);
          }
          if (stage.key === "OFFICER_VERIFY") {
            return ["RESOLUTION_CONFIRMED"].includes(e.action);
          }
          return e.action === stage.key;
        })
      : undefined;
    return {
      ...stage,
      done,
      failed: !done && failedKeys.has(stage.key),
      at: event?.recorded_at ?? null,
      actor: event?.actor_name ?? null,
    };
  });
}

type StepState = "done" | "current" | "pending" | "failed";

function stateOf(stage: StageMatch, isCurrent: boolean): StepState {
  if (stage.done) return "done";
  if (stage.failed) return "failed";
  if (isCurrent) return "current";
  return "pending";
}

function fmtShort(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${date} · ${time}`;
}

function Node({ state, small }: { state: StepState; small?: boolean }) {
  const size = small ? "h-6 w-6" : "h-8 w-8";
  if (state === "done") {
    return (
      <span
        className={cn(
          size,
          "flex shrink-0 items-center justify-center rounded-full bg-success-500 text-white shadow-sm"
        )}
      >
        <Check className="h-4 w-4" strokeWidth={3} />
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span
        className={cn(
          size,
          "flex shrink-0 items-center justify-center rounded-full border-2 border-danger-400 bg-white text-danger-500"
        )}
      >
        <X className="h-4 w-4" strokeWidth={3} />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span
        className={cn(
          size,
          "relative flex shrink-0 items-center justify-center rounded-full border-2 border-primary-500 bg-white text-primary-600"
        )}
      >
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary-500" />
      </span>
    );
  }
  return (
    <span
      className={cn(
        size,
        "flex shrink-0 items-center justify-center rounded-full border-2 border-slate-200 bg-white text-slate-300"
      )}
    >
      <Circle className="h-3.5 w-3.5" />
    </span>
  );
}

export function WorkflowLifecycleCard({ timeline }: Props) {
  if (!timeline) return null;
  const stages = buildStages(timeline);
  const doneCount = stages.filter((s) => s.done).length;
  const firstNotDone = stages.findIndex((s) => !s.done);

  return (
    <div className="overflow-hidden rounded-xl border border-border-soft bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border-soft bg-slate-50/60 px-4 py-3.5 sm:px-5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
          <GitBranch className="h-4 w-4" />
        </span>
        <div>
          <h2 className="text-base font-semibold tracking-tight text-slate-900">
            Work Lifecycle
          </h2>
          <p className="text-sm text-slate-500">
            Track this complaint from citizen report to final closure.
          </p>
        </div>
      </div>

      <div className="p-4 sm:p-5">
        {/* Horizontal stepper — desktop */}
        <div className="hidden overflow-x-auto pb-1 md:block">
          <div className="flex items-start">
            {stages.map((stage, i) => {
              const isCurrent = i === firstNotDone;
              const state = stateOf(stage, isCurrent);
              return (
                <Fragment key={stage.key}>
                  <div className="flex min-w-[92px] flex-1 flex-col items-center text-center">
                    <Node state={state} />
                    <p
                      className={cn(
                        "mt-2 text-xs font-semibold leading-tight",
                        state === "pending" ? "text-slate-300" : "text-slate-700"
                      )}
                    >
                      {stage.label}
                    </p>
                    {state === "done" ? (
                      <p className="mt-0.5 text-[10px] text-slate-400">
                        {stage.at ? fmtShort(stage.at) : "done"}
                      </p>
                    ) : state === "current" ? (
                      <span className="mt-0.5 rounded-full bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                        In progress
                      </span>
                    ) : state === "failed" ? (
                      <span className="mt-0.5 rounded-full bg-danger-50 px-1.5 py-0.5 text-[10px] font-medium text-danger-600">
                        Failed
                      </span>
                    ) : (
                      <span className="mt-0.5 text-[10px] text-slate-300">
                        Pending
                      </span>
                    )}
                  </div>
                  {i < stages.length - 1 && (
                    <div
                      className={cn(
                        "relative mt-[15px] h-0.5 w-[calc(50%-32px)]",
                        state === "done"
                          ? "bg-success-400"
                          : state === "current"
                            ? "bg-primary-400"
                            : "border-t-2 border-dashed border-slate-200"
                      )}
                    />
                  )}
                </Fragment>
              );
            })}
          </div>
        </div>

        {/* Vertical stepper — mobile / tablet */}
        <ol className="divide-y divide-border-soft md:hidden">
          {stages.map((stage, i) => {
            const isCurrent = i === firstNotDone;
            const state = stateOf(stage, isCurrent);
            return (
              <li key={stage.key} className="flex items-center gap-3 py-2">
                <Node state={state} small />
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      "truncate text-sm font-medium",
                      state === "pending" ? "text-slate-400" : "text-slate-800"
                    )}
                  >
                    {stage.label}
                  </p>
                  {(state === "done") && stage.at && (
                    <p className="text-[11px] text-slate-400">
                      {fmtShort(stage.at)}
                      {stage.actor ? ` · ${stage.actor}` : ""}
                    </p>
                  )}
                </div>
                {state === "done" ? (
                  <span className="shrink-0 text-[11px] font-medium text-success-600">
                    Done
                  </span>
                ) : state === "current" ? (
                  <span className="shrink-0 rounded-full bg-primary-50 px-2 py-0.5 text-[11px] font-medium text-primary-600">
                    In progress
                  </span>
                ) : state === "failed" ? (
                  <span className="shrink-0 text-[11px] font-medium text-danger-600">
                    Failed
                  </span>
                ) : (
                  <span className="shrink-0 text-[11px] text-slate-300">
                    Pending
                  </span>
                )}
              </li>
            );
          })}
        </ol>

        <div className="mt-4 flex items-center gap-2 border-t border-border-soft pt-3 text-xs text-slate-500">
          {doneCount === stages.length ? (
            <>
              <Check className="h-3.5 w-3.5 text-success-500" />
              All {stages.length} stages completed.
            </>
          ) : (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
              {doneCount} of {stages.length} stages completed.
            </>
          )}
        </div>
      </div>
    </div>
  );
}