"use client";

import { useEffect, useState } from "react";
import {
  fetchComplaintWorkOrders,
  type WorkOrderDetail,
} from "@/lib/citizen-api";

const TERMINAL = new Set(["COMPLETED", "CLOSED"]);
const DRAFT_ONLY = new Set(["PENDING_APPROVAL", "REJECTED"]);

export type SlaHealth = "ON_TRACK" | "AT_RISK" | "OVERDUE" | "COMPLETED";

export interface SlaInsights {
  loading: boolean;
  order: WorkOrderDetail | null;
  health: SlaHealth | null;
  remainingMs: number;
  elapsedPct: number;
  totalMs: number;
}

function evaluateHealth(
  order: WorkOrderDetail,
  dueAt: string,
  now: number
): {
  health: SlaHealth;
  remainingMs: number;
  elapsedPct: number;
  totalMs: number;
} {
  const due = new Date(dueAt).getTime();
  const created = new Date(order.created_at).getTime();
  const totalMs = order.sla_hours
    ? order.sla_hours * 3600_000
    : Math.max(due - created, 1);
  const remainingMs = due - now;
  const elapsedPct = Math.min(
    Math.max(((now - created) / totalMs) * 100, 0),
    100
  );

  let health: SlaHealth;
  if (TERMINAL.has(order.status)) {
    health = "COMPLETED";
  } else if (remainingMs <= 0) {
    health = "OVERDUE";
  } else if (remainingMs <= totalMs * 0.25) {
    health = "AT_RISK";
  } else {
    health = "ON_TRACK";
  }

  return { health, remainingMs, elapsedPct, totalMs };
}

export function fmtCountdown(ms: number): string {
  const total = Math.abs(Math.round(ms / 60000));
  const d = Math.floor(total / 1440);
  const h = Math.floor((total % 1440) / 60);
  const m = total % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${Math.max(1, m)}m`;
}

export function useSlaInsights(
  complaintId: string,
  enabled = true
): SlaInsights {
  const [order, setOrder] = useState<WorkOrderDetail | null>(null);
  const [now, setNow] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    const load = () => {
      fetchComplaintWorkOrders(complaintId)
        .then((list) => {
          if (cancelled) return;
          const orders = list?.work_orders ?? [];
          const active =
            orders.find((o) => !DRAFT_ONLY.has(o.status)) ?? orders[0] ?? null;
          setOrder(active);
          setNow(Date.now());
        })
        .catch(() => {
          // SLA is advisory — a failure must never block the complaint page.
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    };

    load();
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [complaintId, enabled]);

  if (!enabled) {
    return { loading: false, order: null, health: null, remainingMs: 0, elapsedPct: 0, totalMs: 0 };
  }

  if (!order || !order.due_at || DRAFT_ONLY.has(order.status)) {
    return { loading, order, health: null, remainingMs: 0, elapsedPct: 0, totalMs: 0 };
  }

  const { health, remainingMs, elapsedPct, totalMs } = evaluateHealth(
    order,
    order.due_at,
    now
  );

  return { loading, order, health, remainingMs, elapsedPct, totalMs };
}