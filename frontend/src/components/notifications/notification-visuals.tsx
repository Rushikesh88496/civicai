"use client";

import * as React from "react";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  ClipboardList,
  FileWarning,
  Handshake,
  Inbox,
  MailWarning,
  MapPinned,
  MessageSquare,
  RefreshCw,
  ShieldAlert,
  Workflow,
} from "lucide-react";

interface NotificationVisual {
  icon: React.ReactNode;
  tone: string;
}

const FALLBACK: NotificationVisual = {
  icon: <Bell className="h-4 w-4" />,
  tone: "text-slate-500",
};

const BY_TYPE: Record<string, NotificationVisual> = {
  COMPLAINT_RECEIVED: { icon: <Inbox className="h-4 w-4" />, tone: "text-primary-600" },
  WARD_ALERT: { icon: <MapPinned className="h-4 w-4" />, tone: "text-success-600" },
  AI_COMPLETE: { icon: <Workflow className="h-4 w-4" />, tone: "text-ai-600" },
  PRIORITY_ASSIGNED: { icon: <ClipboardList className="h-4 w-4" />, tone: "text-ai-600" },
  PRIORITY_CHANGE: { icon: <RefreshCw className="h-4 w-4" />, tone: "text-ai-600" },
  WORK_ORDER_CREATED: { icon: <Workflow className="h-4 w-4" />, tone: "text-teal-600" },
  P1_ALERT: { icon: <AlertTriangle className="h-4 w-4" />, tone: "text-danger-600" },
  WORKER_ASSIGNED: { icon: <Handshake className="h-4 w-4" />, tone: "text-info-600" },
  NEW_ASSIGNMENT: { icon: <Handshake className="h-4 w-4" />, tone: "text-info-600" },
  REASSIGNMENT: { icon: <RefreshCw className="h-4 w-4" />, tone: "text-warning-600" },
  REPAIR_STARTED: { icon: <Workflow className="h-4 w-4" />, tone: "text-warning-600" },
  WORK_ORDER_COMPLETED: {
    icon: <CheckCircle2 className="h-4 w-4" />,
    tone: "text-success-600",
  },
  WORK_ORDER_REOPENED: { icon: <RefreshCw className="h-4 w-4" />, tone: "text-warning-600" },
  RESOLVED: { icon: <CheckCircle2 className="h-4 w-4" />, tone: "text-success-600" },
  ESCALATION: { icon: <ShieldAlert className="h-4 w-4" />, tone: "text-danger-600" },
  HUMAN_REVIEW: { icon: <FileWarning className="h-4 w-4" />, tone: "text-warning-600" },
  SLA_RISK: { icon: <MailWarning className="h-4 w-4" />, tone: "text-warning-600" },
  MESSAGE: { icon: <MessageSquare className="h-4 w-4" />, tone: "text-primary-600" },
};

export function notificationVisual(type: string): NotificationVisual {
  return BY_TYPE[type] ?? FALLBACK;
}