// Human-friendly labels and date formatting for the citizen dashboard.

export const CATEGORY_LABELS: Record<string, string> = {
  ROAD: "Roads",
  SANITATION: "Sanitation",
  WATER: "Water",
  ELECTRICITY: "Electricity",
  PUBLIC_SAFETY: "Public Safety",
  PARKS: "Parks & Recreation",
  STREET_LIGHTING: "Street Lighting",
  OTHER: "Other",
};

export const STATUS_LABELS: Record<string, string> = {
  OPEN: "Open",
  IN_PROGRESS: "In Progress",
  RESOLVED: "Resolved",
  ESCALATED: "Escalated",
  SUBMITTED: "Submitted",
  AI_ANALYZING: "AI Analyzing",
  EVIDENCE_VERIFIED: "Evidence Verified",
  WARD_IDENTIFIED: "Ward Identified",
  PRIORITIZED: "Prioritized",
  DEPARTMENT_ASSIGNED: "Department Assigned",
  WORK_ORDER_CREATED: "Work Order Created",
  WORKER_ASSIGNED: "Worker Assigned",
  CITIZEN_VERIFIED: "Citizen Verified",
  CLOSED: "Closed",
};

export const PRIORITY_LABELS: Record<string, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  CRITICAL: "Critical",
};

export function categoryLabel(value: string): string {
  return CATEGORY_LABELS[value] ?? value;
}

export function statusLabel(value: string): string {
  return STATUS_LABELS[value] ?? value;
}

export function priorityLabel(value: string): string {
  return PRIORITY_LABELS[value] ?? value;
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function timeAgo(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  const intervals: Array<[number, string]> = [
    [31536000, "year"],
    [2592000, "month"],
    [604800, "week"],
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ];
  for (const [secondsIn, label] of intervals) {
    const count = Math.floor(seconds / secondsIn);
    if (count >= 1) {
      return `${count} ${label}${count > 1 ? "s" : ""} ago`;
    }
  }
  return "just now";
}

export function initials(name: string | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}