"use client";

// Derived, deterministic UI helpers that map a complaint's real backend status
// onto a human-friendly lifecycle stage and progress. No synthetic data is
// involved — the stage order mirrors the actual pipeline statuses the backend
// emits (submit → AI triage → routing → dispatch → field work → verification →
// resolved → closed).

export const COMPLAINT_STAGE_ORDER: readonly string[] = [
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
];

/** Legacy / out-of-band statuses map onto an explicit stage position. */
const STAGE_OVERRIDES: Record<string, number> = {
  OPEN: 4,
  ESCALATED: 13,
  RETURNED_FOR_REWORK: 10,
  REWORK_REQUESTED: 10,
};

export const CLOSED_STATUSES: readonly string[] = ["RESOLVED", "CLOSED"];

export function isClosedStatus(status: string): boolean {
  return CLOSED_STATUSES.includes(status);
}

export function complaintStageIndex(status: string): number {
  const override = STAGE_OVERRIDES[status];
  if (override !== undefined) return override;
  const index = COMPLAINT_STAGE_ORDER.indexOf(status);
  return index >= 0 ? index : 0;
}

/** 0–100 progress of the lifecycle derived purely from the status value. */
export function complaintProgress(status: string): number {
  if (isClosedStatus(status)) return 100;
  if (status === "ESCALATED") return 100;
  const index = complaintStageIndex(status);
  return Math.round(((index + 1) / COMPLAINT_STAGE_ORDER.length) * 100);
}

export type StageTone = "primary" | "success" | "warning" | "danger";

export function complaintStageTone(status: string): StageTone {
  if (isClosedStatus(status) || status === "CITIZEN_VERIFIED") return "success";
  if (status === "ESCALATED") return "danger";
  if (status === "RETURNED_FOR_REWORK" || status === "REWORK_REQUESTED") {
    return "warning";
  }
  if (
    status === "IN_PROGRESS" ||
    status === "WORK_COMPLETED" ||
    status === "WORKER_ASSIGNED" ||
    status === "WORK_ORDER_CREATED"
  ) {
    return "warning";
  }
  return "primary";
}

/**
 * Short human label for the current lifecycle phase, e.g. "Priority assigned"
 * or "Field work in progress". Falls back to the app-wide status label.
 */
export function complaintStageLabel(status: string): string {
  const labels: Record<string, string> = {
    SUBMITTED: "Submitted",
    AI_ANALYZING: "AI analysis",
    EVIDENCE_VERIFIED: "Evidence verified",
    WARD_IDENTIFIED: "Ward identified",
    PRIORITIZED: "Priority assigned",
    DEPARTMENT_ASSIGNED: "Department assigned",
    WORK_ORDER_CREATED: "Work order created",
    WORKER_ASSIGNED: "Worker assigned",
    IN_PROGRESS: "Field work in progress",
    WORK_COMPLETED: "Work finished",
    EVIDENCE_SUBMITTED: "Evidence submitted",
    CITIZEN_VERIFIED: "Citizen verification",
    RESOLVED: "Resolved",
    CLOSED: "Closed",
    OPEN: "Open",
    ESCALATED: "Escalated",
    RETURNED_FOR_REWORK: "Returned for rework",
    REWORK_REQUESTED: "Rework requested",
  };
  return labels[status] ?? status.replace(/_/g, " ").toLowerCase();
}