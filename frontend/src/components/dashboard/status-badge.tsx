"use client";

import { Badge } from "@/components/ui/badge";
import {
  statusLabel,
  priorityLabel,
  categoryLabel,
} from "@/components/dashboard/format";

const STATUS_VARIANT: Record<
  string,
  "success" | "warning" | "secondary" | "destructive" | "info" | "ai"
> = {
  OPEN: "secondary",
  IN_PROGRESS: "warning",
  WORK_COMPLETED: "info",
  EVIDENCE_SUBMITTED: "ai",
  RETURNED_FOR_REWORK: "warning",
  REWORK_REQUESTED: "warning",
  RESOLVED: "success",
  ESCALATED: "destructive",
  SUBMITTED: "secondary",
  AI_ANALYZING: "ai",
  EVIDENCE_VERIFIED: "ai",
  WARD_IDENTIFIED: "ai",
  PRIORITIZED: "ai",
  DEPARTMENT_ASSIGNED: "warning",
  WORK_ORDER_CREATED: "warning",
  WORKER_ASSIGNED: "warning",
  CITIZEN_VERIFIED: "success",
  CLOSED: "success",
};

const PRIORITY_VARIANT: Record<string, "secondary" | "warning" | "destructive"> = {
  LOW: "secondary",
  MEDIUM: "warning",
  HIGH: "destructive",
  CRITICAL: "destructive",
};

const CATEGORY_VARIANT: Record<string, "outline" | "default"> = {
  OTHER: "outline",
};

export function StatusBadge({ value }: { value: string }) {
  const variant = STATUS_VARIANT[value] ?? "secondary";
  return <Badge variant={variant}>{statusLabel(value)}</Badge>;
}

export function PriorityBadge({ value }: { value: string }) {
  const variant = PRIORITY_VARIANT[value] ?? "secondary";
  return <Badge variant={variant}>{priorityLabel(value)}</Badge>;
}

export function CategoryBadge({ value }: { value: string }) {
  const variant = CATEGORY_VARIANT[value] ?? "outline";
  return <Badge variant={variant}>{categoryLabel(value)}</Badge>;
}