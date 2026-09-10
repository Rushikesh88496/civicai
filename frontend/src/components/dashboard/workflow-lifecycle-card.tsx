"use client";

import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { formatDateTime } from "@/components/dashboard/format";
import type { ComplaintTimeline } from "@/lib/citizen-api";

interface Props {
  timeline: ComplaintTimeline | null;
}

interface Stage {
  key: string;
  label: string;
  hint: string;
  /** Returns true when the merged event trail proves this stage happened. */
  matched: (summary: StageSummary) => boolean;
}

interface StageSummary {
  complaintStatuses: Set<string>;
  workActions: Set<string>;
  workStatuses: Set<string>;
}

interface StageMatch extends Stage {
  done: boolean;
  at: string | null;
  actor: string | null;
}

/**
 * Part 32 — full human-in-the-loop work lifecycle for a complaint.
 *
 * Merges the complaint status trail with the work-order milestone trail so a
 * citizen and an officer see one authoritative pipeline:
 *
 *   submitted → triaged → routed → officer review → signed (approved) →
 *   accepted → in-progress → evidence → AI verify → officer verify →
 *   resolved → closed
 *
 * An AI recommendation is deliberately NOT shown as an "assignment": only an
 * officer-approved (signed) work order is an official assignment (Part 32).
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
    label: "Triaged",
    hint: "AI assessed severity, urgency and infrastructure type.",
    matched: (s) =>
      ["PRIORITIZED", "OPEN", "IN_REVIEW", "DEPARTMENT_ASSIGNED"].some((st) =>
        s.complaintStatuses.has(st)
      ),
  },
  {
    key: "ROUTED",
    label: "Routed",
    hint: "Department responsible for the issue was decided.",
    matched: (s) =>
      s.complaintStatuses.has("DEPARTMENT_ASSIGNED") ||
      s.workActions.has("DISPATCH"),
  },
  {
    key: "OFFICER_REVIEW",
    label: "Officer review",
    hint: "Draft work order awaiting an officer's decision.",
    matched: (s) =>
      s.workActions.has("DISPATCH") || s.workStatuses.has("PENDING_APPROVAL"),
  },
  {
    key: "SIGNED",
    label: "Signed & assigned",
    hint: "Officer approved the work order — official assignment created.",
    matched: (s) =>
      ["APPROVE", "ASSIGN", "REASSIGN"].some((a) => s.workActions.has(a)),
  },
  {
    key: "ACCEPTED",
    label: "Accepted",
    hint: "Field worker accepted the assignment.",
    matched: (s) => s.workActions.has("ACCEPT"),
  },
  {
    key: "IN_PROGRESS",
    label: "In progress",
    hint: "Work commenced at the site.",
    matched: (s) =>
      s.workActions.has("START_WORK") || s.complaintStatuses.has("IN_PROGRESS"),
  },
  {
    key: "EVIDENCE",
    label: "Evidence captured",
    hint: "Before/after photos and notes logged by the worker.",
    matched: (s) =>
      ["PHOTO_BEFORE", "PHOTO_AFTER", "NOTE_ADDED", "CHECK_IN"].some((a) =>
        s.workActions.has(a)
      ),
  },
  {
    key: "AI_VERIFY",
    label: "AI verification",
    hint: "Repair evidence passed the automated verification pass.",
    matched: (s) =>
      s.workActions.has("COMPLETE_WORK") || s.complaintStatuses.has("RESOLVED"),
  },
  {
    key: "OFFICER_VERIFY",
    label: "Officer verification",
    hint: "Officer signed off on the completed work.",
    matched: (s) => s.complaintStatuses.has("RESOLVED"),
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

const STAGE_LABEL: Record<string, string> = {
  SUBMITTED: "Complaint submitted",
  TRIAGED: "Complaint triaged",
  ROUTED: "Routed to department",
  OFFICER_REVIEW: "Draft awaiting officer",
  SIGNED: "Official assignment confirmed",
  ACCEPTED: "Worker accepted assignment",
  IN_PROGRESS: "Work in progress",
  EVIDENCE: "Evidence captured",
  AI_VERIFY: "AI verification passed",
  OFFICER_VERIFY: "Officer verification passed",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};

function buildSummary(timeline: ComplaintTimeline): StageMatch[] {
  const complaintStatuses = new Set(
    timeline.events.map((e) => e.status)
  );
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

  return STAGES.map((stage) => {
    const done = stage.matched(summary);
    const event = done ? [...all].reverse().find((e) => {
      if (stage.key === "SIGNED") {
        return ["APPROVE", "ASSIGN", "REASSIGN"].includes(e.action);
      }
      if (stage.key === "EVIDENCE") {
        return ["PHOTO_BEFORE", "PHOTO_AFTER", "NOTE_ADDED", "CHECK_IN"].includes(
          e.action
        );
      }
      return e.action === stage.key;
    }) : undefined;
    return { ...stage, done, at: event?.recorded_at ?? null, actor: event?.actor_name ?? null };
  });
}

export function WorkflowLifecycleCard({ timeline }: Props) {
  if (!timeline) return null;
  const stages = buildSummary(timeline);
  const doneCount = stages.filter((s) => s.done).length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary-600" /> Work lifecycle
        </CardTitle>
        <CardDescription>
          One pipeline from report to closure — triage, routing, officer approval
          and field work. An AI recommendation becomes an official assignment
          only once an officer signs it off.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="relative ml-2 border-l-2 border-border-soft pl-6">
          {stages.map((stage) => (
            <li key={stage.key} className="relative pb-5 last:pb-0">
              <span
                className={`absolute -left-[27px] flex h-6 w-6 items-center justify-center rounded-full border-2 bg-surface ${
                  stage.done
                    ? "border-primary-600 text-primary-600"
                    : "border-slate-300 text-slate-300"
                }`}
              >
                {stage.done ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <Circle className="h-3.5 w-3.5" />
                )}
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`text-sm font-medium ${
                    stage.done ? "text-slate-900" : "text-slate-400"
                  }`}
                >
                  {STAGE_LABEL[stage.key]}
                </span>
                {stage.done && stage.at && (
                  <span className="text-xs text-slate-400">
                    {formatDateTime(stage.at)}
                    {stage.actor ? ` · ${stage.actor}` : ""}
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-xs text-slate-500">{stage.hint}</p>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex items-center gap-2 text-sm text-slate-500">
          {doneCount === stages.length ? (
            <>
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              Completed all {stages.length} stages.
            </>
          ) : (
            <>
              <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
              {doneCount} of {stages.length} stages completed.
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}