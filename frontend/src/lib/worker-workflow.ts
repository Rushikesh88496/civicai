// --------------------------------------------------------------------------- //
// Worker job workflow — derives the 7-step task progress from REAL backend state.
//
// Nothing here invents progress: every step maps to a server-side fact
// (accepted_at, activity rows, evidence timestamp, verification verdict /
// review). The UI shows "current status" + "next action" from these facts only.
//
// The field worker moves the order IN_PROGRESS → WORK_COMPLETED (finish) →
// EVIDENCE_SUBMITTED (submit resolution evidence). The complaint is only
// RESOLVED when an officer approves the resolution — the worker never resolves
// it and neither does the AI (the officer's review is the final step), so the
// worker's step list ends at "Officer Verification", which is status-only. An
// officer review is only "done" once they actually approve/decide
// (reviewed_at set).
//
// When an officer REQUEST_REWORKs, the order returns to RETURNED_FOR_REWORK and
// the worker must restart the cycle: a FRESH GPS check-in (recorded after the
// rework request) unlocks START REWORK, which resets the job to IN_PROGRESS.
// Only facts recorded at/after the rework request count toward the rework
// cycle — stale round-1 timestamps and verification rows are ignored — so the
// same step list accurately tracks the rework run while the job is reworking.
// --------------------------------------------------------------------------- //

import type {
  WorkerOrderDetail,
  WorkerVerification,
  WorkOrderActivity,
} from "@/lib/field-worker-api";

export interface WorkflowStep {
  key: string;
  label: string;
  hint: string;
  done: boolean;
  current: boolean;
}

export interface WorkflowState {
  steps: WorkflowStep[];
  doneCount: number;
  total: number;
  currentStatus: string;
  nextAction: string;
  /** First pending worker action (drives the sticky primary CTA). Null when no action is available. */
  pendingStepKey:
    | "accept"
    | "check-in"
    | "start"
    | "rework"
    | "finish"
    | "evidence"
    | null;
  verified: boolean;
  /** ISO timestamp of the latest REWORK_REQUESTED decision (null when never reworked). */
  reworkRequestedAt: string | null;
  /** Rework-aware cycle facts (a fresh GPS check-in, started/finished/evidence
   *  performed in the current run). Mirrors the workflow steps without the
   *  verification stages — used by the panel to render the right inline action. */
  checkedIn: boolean;
  started: boolean;
  finished: boolean;
  evidenceSubmitted: boolean;
}

export const WORKFLOW_STEP_COUNT = 6;

// The server records actual check-ins as EN_ROUTE / ARRIVED activity rows
// (WorkerCheckInIn.activity_type). "CHECK_IN" is the older canonical marker —
// accept all three so a recorded check-in is never missed and START WORK is
// unlocked exactly when the backend says a check-in exists.
const CHECK_IN_TYPES = ["CHECK_IN", "EN_ROUTE", "ARRIVED"] as const;

const hasActivity = (activities: WorkOrderActivity[], type: string) =>
  activities.some((a) => a.activity_type === type);

const hasAnyActivity = (activities: WorkOrderActivity[], types: readonly string[]) =>
  types.some((t) => hasActivity(activities, t));

const hasActivityAfter = (
  activities: WorkOrderActivity[],
  types: readonly string[],
  sinceMs: number
) =>
  activities.some(
    (a) =>
      (types as readonly string[]).includes(a.activity_type) &&
      new Date(a.recorded_at).getTime() >= sinceMs
  );

/** The latest time an officer REQUEST_REWORKed this job (null when never). */
export function latestReworkRequestedAt(
  detail: WorkerOrderDetail | null
): string | null {
  const history = detail?.status_history ?? [];
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (history[i].action === "REWORK_REQUESTED") {
      return history[i].recorded_at;
    }
  }
  return null;
}

/** The most recent GPS check-in activity (or null when never checked in).
 *
 * During a rework cycle only check-ins recorded AFTER the rework request count
 * (a fresh fix proves the worker came back on site) — stale round-1 check-ins
 * are ignored. Outside a rework the latest check-in is returned. */
export function checkInActivity(
  detail: WorkerOrderDetail | null
): WorkOrderActivity | null {
  const activities = detail?.activities ?? [];
  const reworkRequestedAt = latestReworkRequestedAt(detail);
  const sinceMs = reworkRequestedAt
    ? new Date(reworkRequestedAt).getTime()
    : null;
  for (let i = activities.length - 1; i >= 0; i -= 1) {
    const activity = activities[i];
    if (!(CHECK_IN_TYPES as readonly string[]).includes(activity.activity_type)) {
      continue;
    }
    if (sinceMs === null || new Date(activity.recorded_at).getTime() >= sinceMs) {
      return activity;
    }
  }
  return null;
}

export function buildWorkflow(
  detail: WorkerOrderDetail | null,
  verification: WorkerVerification | null
): WorkflowState {
  const order = detail?.work_order ?? null;
  const activities = detail?.activities ?? [];

  const reworkRequestedAt = latestReworkRequestedAt(detail);
  const reworking = reworkRequestedAt != null;
  const t0Ms = reworking ? new Date(reworkRequestedAt!).getTime() : null;
  // Only facts recorded at/after the rework request count in a rework cycle.
  const withinReworkWindow = (iso: string | null | undefined): boolean =>
    !!iso && t0Ms !== null && new Date(iso).getTime() >= t0Ms;

  const accepted = !!order?.accepted_at;
  const checkedIn = reworking
    ? checkInActivity(detail) != null
    : hasAnyActivity(activities, CHECK_IN_TYPES);
  const started = reworking
    ? withinReworkWindow(order?.started_at) ||
      hasActivityAfter(activities, ["START_REWORK"], t0Ms!)
    : !!order?.started_at || hasActivity(activities, "START_WORK");
  const finished = reworking
    ? withinReworkWindow(order?.completed_at) ||
      hasActivityAfter(activities, ["FINISH_WORK", "COMPLETE_WORK"], t0Ms!)
    : !!order?.completed_at ||
      hasActivity(activities, "FINISH_WORK") ||
      hasActivity(activities, "COMPLETE_WORK");
  const evidenceSubmitted =
    order?.status === "EVIDENCE_SUBMITTED" ||
    order?.status === "COMPLETED" ||
    (!!order?.evidence_submitted_at &&
      (!reworking || withinReworkWindow(order?.evidence_submitted_at)));
  // The field worker's own actions end at evidence submission. After that the
  // job is with the officer: the worker only SEES the final "Officer
  // Verification" step (no AI step — AI/vendor verification is an officer-side
  // tool); it is done only once the officer actually reviews (reviewed_at set).
  const officerVerified =
    verification != null &&
    verification.reviewed_at != null &&
    (!reworking || withinReworkWindow(verification.reviewed_at));
  const completed = officerVerified && finished;

  const ordersFlat = [
    { key: "accept", label: "Accept Task", hint: "Confirm you take on this job", done: accepted },
    { key: "check-in", label: "Check In / GPS", hint: "Report your location on site", done: checkedIn },
    { key: "start", label: "Start Work", hint: "Begin the on-ground repair", done: started },
    { key: "finish", label: "Finish Work", hint: "Mark the physical work as done", done: finished },
    {
      key: "evidence",
      label: "Submit Evidence",
      hint: "Attach photos + submit the resolution evidence",
      done: evidenceSubmitted,
    },
    {
      key: "officer-verification",
      label: "Officer Verification",
      hint: "Waiting for the officer to verify the repair",
      done: officerVerified,
    },
  ];

  const firstUndone = ordersFlat.find((s) => !s.done);
  const steps: WorkflowStep[] = ordersFlat.map((s) => ({
    key: s.key,
    label: s.label,
    hint: s.hint,
    done: s.done,
    current: s.key === firstUndone?.key,
  }));

  const doneCount = steps.filter((s) => s.done).length;

  // Current status — a single concise sentence driven by the real state.
  let currentStatus: string;
  if (completed) {
    currentStatus = officerVerified ? "Completed — resolution verified" : "Completed";
  } else if (officerVerified) {
    currentStatus = "Officer requested follow-up";
  } else if (finished && evidenceSubmitted) {
    currentStatus = reworking
      ? "Rework finished — awaiting officer verification"
      : "Work finished — awaiting officer verification";
  } else if (reworking && !started) {
    currentStatus = "Returned for rework — officer requested fixes";
  } else if (reworking && finished) {
    currentStatus = "Rework finished — submit resolution evidence";
  } else if (reworking) {
    currentStatus = "Rework in progress";
  } else if (finished) {
    currentStatus = "Work finished — evidence still pending";
  } else if (started) {
    currentStatus = "In progress";
  } else if (accepted) {
    currentStatus = "Accepted — head to the location";
  } else {
    currentStatus = "Assigned — awaiting acceptance";
  }

  // Next action — the single most useful instruction (no reasoning exposed).
  let nextAction: string;
  let pendingStepKey: WorkflowState["pendingStepKey"] = null;

  if (completed) {
    nextAction = officerVerified
      ? "Nothing pending — this job is verified and closed."
      : "Nothing pending — this job is complete.";
  } else if (reworking && !checkedIn) {
    // Rework always starts with a FRESH GPS check-in (never a stale round-1 fix).
    nextAction = "Re-check in with your GPS location to restart the repair.";
    pendingStepKey = "check-in";
  } else if (reworking && !started) {
    nextAction = "Start the rework to resume the repair.";
    pendingStepKey = "rework";
  } else if (officerVerified) {
    nextAction = "An officer requested follow-up on this job — continue the repairs.";
  } else if (!accepted) {
    nextAction = "Accept this task to begin the field workflow.";
    pendingStepKey = "accept";
  } else if (!checkedIn) {
    nextAction = "Check in with your GPS location before starting.";
    pendingStepKey = "check-in";
  } else if (!started) {
    nextAction = "Start work to begin the repair.";
    pendingStepKey = "start";
  } else if (!finished) {
    nextAction = "Finish the physical work and record the completed time.";
    pendingStepKey = "finish";
  } else if (!evidenceSubmitted) {
    nextAction = "Submit the resolution evidence to hand the job to officer verification.";
    pendingStepKey = "evidence";
  } else if (!officerVerified) {
    nextAction = "Evidence submitted — waiting for the officer to verify the repair.";
  } else {
    nextAction = "Officer review done — job is complete.";
  }

  return {
    steps,
    doneCount,
    total: WORKFLOW_STEP_COUNT,
    currentStatus,
    nextAction,
    pendingStepKey,
    verified: officerVerified,
    reworkRequestedAt,
    checkedIn,
    started,
    finished,
    evidenceSubmitted,
  };
}

/** True when ``iso`` falls on ``ref``'s calendar day (device-local time). */
export function isSameLocalDay(iso: string | null | undefined, ref: Date): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return (
    d.getFullYear() === ref.getFullYear() &&
    d.getMonth() === ref.getMonth() &&
    d.getDate() === ref.getDate()
  );
}