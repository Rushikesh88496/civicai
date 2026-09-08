"use client";

import * as React from "react";
import { ShieldAlert, Play, Settings2, Trash2, Plus, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { formatDateTime } from "@/components/dashboard/format";
import {
  fetchSlaOrders,
  fetchSlaPolicies,
  fetchSlaRun,
  runSlaMonitor,
  createSlaPolicy,
  updateSlaPolicy,
  deleteSlaPolicy,
  type OrderSlaSnapshot,
  type SlaCounts,
  type SlaPolicy,
  type SlaState,
} from "@/lib/officer-api";

const DEPARTMENTS = [
  "WATER",
  "ROADS",
  "ELECTRICAL",
  "WASTE",
  "DRAINAGE",
  "PARKS",
  "EMERGENCY_DISASTER",
];

const PRIORITIES = ["P1_CRITICAL", "P2_HIGH", "P3_MEDIUM", "P4_LOW"];

const CATEGORIES = [
  "ROAD",
  "SANITATION",
  "WATER",
  "ELECTRICITY",
  "PUBLIC_SAFETY",
  "PARKS",
  "STREET_LIGHTING",
  "OTHER",
];

const STATE_META: Record<SlaState, { label: string; badge: string | "outline"; text: string; bar: string }> = {
  ON_TRACK: { label: "On Track", badge: "success", text: "text-success-600", bar: "bg-success-500" },
  AT_RISK: { label: "At Risk", badge: "warning", text: "text-warning-600", bar: "bg-warning-500" },
  BREACHED: { label: "Breached", badge: "destructive", text: "text-danger-600", bar: "bg-danger-500" },
  COMPLETED: { label: "Completed", badge: "secondary", text: "text-slate-500", bar: "bg-slate-400" },
};

type FilterTab = SlaState | "ALL";

const defaultCounts: SlaCounts = {
  open: 0,
  on_track: 0,
  at_risk: 0,
  breached: 0,
  completed: 0,
  no_deadline: 0,
};

function stateBadge(state: SlaState) {
  const meta = STATE_META[state];
  return <Badge variant={meta.badge as "success"}>{meta.label}</Badge>;
}

function stateBadgeOutlined(state: SlaState) {
  const meta = STATE_META[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", meta.text)}>
      <span className={cn("h-2 w-2 rounded-full", meta.bar)} />
      {meta.label}
    </span>
  );
}

function ProgressBar({ snap }: { snap: OrderSlaSnapshot }) {
  const meta = STATE_META[snap.state];
  const pct = Math.min(100, Math.round(snap.progress * 100));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full min-w-16 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn("h-full", meta.bar)}
          style={{ width: `${Math.max(4, pct)}%` }}
          title={`${pct}% of window elapsed`}
        />
      </div>
      <span className="text-[11px] tabular-nums text-slate-500">{pct}%</span>
    </div>
  );
}

function StatChip({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border-soft px-3 py-2">
      <div className={cn("text-xl font-bold", tone ?? "text-slate-900")}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

export function SlaMonitor() {
  const [orders, setOrders] = React.useState<OrderSlaSnapshot[]>([]);
  const [counts, setCounts] = React.useState<SlaCounts>(defaultCounts);
  const [policies, setPolicies] = React.useState<SlaPolicy[]>([]);
  const [lastRunAt, setLastRunAt] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<FilterTab>("ALL");

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [running, setRunning] = React.useState(false);
  const [showPolicies, setShowPolicies] = React.useState(false);
  const [tick, setTick] = React.useState(0);

  const load = React.useCallback(async () => {
    const [page, policiesRes, run] = await Promise.all([
      fetchSlaOrders({ page: 1, page_size: 50 }),
      fetchSlaPolicies(),
      fetchSlaRun(),
    ]);
    setCounts(page.counts);
    setOrders(page.items);
    setPolicies(policiesRes);
    setLastRunAt(run?.structured_result?.checked_at ?? run?.ended_at ?? null);
  }, []);

  React.useEffect(() => {
    let active = true;
    Promise.all([
      fetchSlaOrders({ page: 1, page_size: 50 }),
      fetchSlaPolicies(),
      fetchSlaRun(),
    ])
      .then(([page, policiesRes, run]) => {
        if (!active) return;
        setCounts(page.counts);
        setOrders(page.items);
        setPolicies(policiesRes);
        setLastRunAt(run?.structured_result?.checked_at ?? run?.ended_at ?? null);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load SLA monitor.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  // Countdown keeps ticking by re-pulling the board on an interval.
  React.useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000);
    return () => clearInterval(id);
  }, []);

  const triggerRun = async () => {
    setRunning(true);
    setError(null);
    try {
      await runSlaMonitor();
      await load();
      setTick((t) => t + 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "SLA check failed.");
    } finally {
      setRunning(false);
    }
  };

  const visible = React.useMemo(() => {
    const items = tab === "ALL" ? orders : orders.filter((o) => o.state === tab);
    return items.slice().sort(sortSnapshots);
  }, [orders, tab]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-primary-600" />
            SLA Monitoring
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="h-5 animate-pulse rounded bg-slate-100" />
            <div className="h-5 animate-pulse rounded bg-slate-100" />
            <div className="h-5 animate-pulse rounded bg-slate-100" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-primary-600" />
            SLA Monitoring
          </CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            {lastRunAt && (
              <span className="text-xs text-slate-400">
                Last check {formatDateTime(lastRunAt)}
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowPolicies((s) => !s)}
            >
              <Settings2 className="mr-1.5 h-4 w-4" />
              {showPolicies ? "Hide Policies" : "SLA Policies"}
            </Button>
            <Button size="sm" onClick={triggerRun} disabled={running}>
              <Play className={cn("mr-1.5 h-4 w-4", running && "hidden")} />
              {running ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : null}
              {running ? "Checking…" : "Run SLA Check"}
            </Button>
          </div>
        </div>
        <CardDescription>
          Deadlines resolved from your configurable priority / department / category rules.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {error ? (
          <ErrorState
            title="Unable to load SLA monitor"
            description={error}
            action={<Button variant="outline" onClick={() => setTick((t) => t + 1)}>Retry</Button>}
          />
        ) : (
          <>
            {/* Count strip */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <StatChip
                label="Open"
                value={counts.open}
                tone={counts.breached > 0 ? "text-danger-600" : "text-slate-900"}
              />
              <StatChip label="On Track" value={counts.on_track} tone="text-success-600" />
              <StatChip label="At Risk" value={counts.at_risk} tone="text-warning-600" />
              <StatChip
                label="Breached"
                value={counts.breached}
                tone={counts.breached > 0 ? "text-danger-600" : "text-slate-900"}
              />
              <StatChip label="Completed" value={counts.completed} tone="text-slate-500" />
              <StatChip label="No Deadline" value={counts.no_deadline} tone="text-slate-500" />
            </div>

            {/* Filter tabs */}
            <div className="flex flex-wrap gap-2">
              {(["ALL", "AT_RISK", "BREACHED", "ON_TRACK", "COMPLETED"] as FilterTab[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                    tab === t
                      ? "border-primary-600 bg-primary-600 text-white"
                      : "border-border-soft text-slate-600 hover:border-border-strong"
                  )}
                >
                  {t === "ALL" ? "All" : STATE_META[t].label}
                </button>
              ))}
            </div>

            {/* Order list: desktop table + mobile cards */}
            {visible.length === 0 ? (
              <EmptyState
                icon={<ShieldAlert className="h-8 w-8 text-slate-400" />}
                title="No SLA entries"
                description="Open a work order and it will appear here with its SLA health."
              />
            ) : (
              <>
                <div className="hidden overflow-x-auto rounded-lg border border-border-soft md:block">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-3 py-2">Order</th>
                        <th className="px-3 py-2">Dept</th>
                        <th className="px-3 py-2">Priority</th>
                        <th className="px-3 py-2">Status</th>
                        <th className="px-3 py-2 w-40">Progress</th>
                        <th className="px-3 py-2">Remaining</th>
                        <th className="px-3 py-2">State</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {visible.map((snap) => (
                        <tr key={snap.work_order_id} className="hover:bg-slate-50">
                          <td className="px-3 py-2">
                            <div className="max-w-56 truncate font-medium text-slate-900">
                              {snap.incident ?? snap.work_order_id}
                            </div>
                            {snap.worker_name && (
                              <div className="text-xs text-slate-500">{snap.worker_name}</div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-slate-600">{snap.department}</td>
                          <td className="px-3 py-2">
                            {snap.priority ? <Badge variant="outline">{snap.priority}</Badge> : "—"}
                          </td>
                          <td className="px-3 py-2 text-slate-600">{snap.status}</td>
                          <td className="px-3 py-2">
                            <ProgressBar snap={snap} />
                          </td>
                          <td className="px-3 py-2 tabular-nums text-slate-700">
                            {snap.remaining_human ?? "—"}
                          </td>
                          <td className="px-3 py-2">{stateBadge(snap.state)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="grid gap-2 md:hidden">
                  {visible.map((snap) => (
                    <div
                      key={snap.work_order_id}
                      className="rounded-lg border border-border-soft p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="truncate font-medium text-slate-900">
                          {snap.incident ?? snap.work_order_id}
                        </p>
                        {stateBadgeOutlined(snap.state)}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {snap.department}
                        {snap.priority ? ` · ${snap.priority}` : ""} · {snap.status}
                      </p>
                      <div className="mt-2">
                        <ProgressBar snap={snap} />
                      </div>
                      <p className="mt-1 text-xs tabular-nums text-slate-700">
                        {snap.remaining_human ?? "No deadline"}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Policies manager */}
            {showPolicies && (
              <PolicyManager policies={policies} onChanged={load} />
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function sortSnapshots(a: OrderSlaSnapshot, b: OrderSlaSnapshot) {
  const rank = (s: OrderSlaSnapshot) =>
    s.state === "BREACHED" ? 0 : s.state === "AT_RISK" ? 1 : s.state === "ON_TRACK" ? 2 : 3;
  const d = rank(a) - rank(b);
  if (d !== 0) return d;
  return (a.remaining_seconds ?? Infinity) - (b.remaining_seconds ?? Infinity);
}

function PolicyManager({
  policies,
  onChanged,
}: {
  policies: SlaPolicy[];
  onChanged: () => Promise<void>;
}) {
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const [editing, setEditing] = React.useState<SlaPolicy | "new" | null>(null);

  return (
    <div className="rounded-lg border border-border-soft p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">SLA Policies</h3>
        {!editing && (
          <Button size="sm" variant="outline" onClick={() => setEditing("new")}>
            <Plus className="mr-1.5 h-4 w-4" /> Add Rule
          </Button>
        )}
      </div>
      {message && <p className="mt-2 text-sm text-success-600">{message}</p>}
      {error && <p className="mt-2 text-sm text-danger-600">{error}</p>}

      {policies.length === 0 && !editing && (
        <p className="mt-3 text-sm text-slate-500">
          No rules yet. Add one to start assigning deadlines.
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {policies.map((p) =>
          editing === p ? (
            <PolicyForm
              key={p.id}
              initial={p}
              busy={busy}
              onSave={async (payload) => {
                setBusy(true);
                setError(null);
                setMessage(null);
                try {
                  await updateSlaPolicy(p.id, payload);
                  await onChanged();
                  setEditing(null);
                  setMessage("Policy updated.");
                } catch (err: unknown) {
                  setError(err instanceof Error ? err.message : "Failed to update policy.");
                } finally {
                  setBusy(false);
                }
              }}
              onCancel={() => setEditing(null)}
            />
          ) : (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border-soft px-3 py-2 text-sm"
            >
              <div>
                <div className="font-medium text-slate-800">
                  <span
                    className={cn(
                      "mr-2 inline-block h-2 w-2 rounded-full",
                      p.active ? "bg-success-500" : "bg-slate-300"
                    )}
                  />
                  {p.name ?? `${p.priority ?? "Any"} / ${p.department ?? "Any"} / ${p.category ?? "Any"}`}
                </div>
                <div className="text-xs text-slate-500">
                  {p.sla_hours}h SLA · warning at {Math.round(p.at_risk_percent * 100)}% ·{" "}
                  {p.escalate_on_breach ? "escalates" : "no escalation"}
                  {!p.active && " · inactive"}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-danger-600"
                  onClick={async () => {
                    setBusy(true);
                    setError(null);
                    setMessage(null);
                    try {
                      await deleteSlaPolicy(p.id);
                      await onChanged();
                      setMessage("Policy deleted.");
                    } catch (err: unknown) {
                      setError(err instanceof Error ? err.message : "Failed to delete policy.");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </li>
          )
        )}
      </ul>

      {editing === "new" && (
        <div className="mt-3">
          <PolicyForm
            initial={null}
            busy={busy}
            onSave={async (payload) => {
              setBusy(true);
              setError(null);
              setMessage(null);
              try {
                await createSlaPolicy(payload);
                await onChanged();
                setEditing(null);
                setMessage("Policy created.");
              } catch (err: unknown) {
                setError(err instanceof Error ? err.message : "Failed to create policy.");
              } finally {
                setBusy(false);
              }
            }}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}
    </div>
  );
}

function PolicyForm({
  initial,
  busy,
  onSave,
  onCancel,
}: {
  initial: SlaPolicy | null;
  busy: boolean;
  onSave: (payload: {
    name?: string | null;
    priority?: string | null;
    department?: string | null;
    category?: string | null;
    sla_hours: number;
    at_risk_percent: number;
    escalate_on_breach: boolean;
    active: boolean;
  }) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = React.useState(initial?.name ?? "");
  const [priority, setPriority] = React.useState(initial?.priority ?? "");
  const [department, setDepartment] = React.useState(initial?.department ?? "");
  const [category, setCategory] = React.useState(initial?.category ?? "");
  const [slaHours, setSlaHours] = React.useState(String(initial?.sla_hours ?? 24));
  const [atRisk, setAtRisk] = React.useState(String(initial?.at_risk_percent ?? 0.75));
  const [escalate, setEscalate] = React.useState(initial?.escalate_on_breach ?? true);
  const [active, setActive] = React.useState(initial?.active ?? true);
  const [localError, setLocalError] = React.useState<string | null>(null);

  const submit = () => {
    const hours = Number(slaHours);
    const percent = Number(atRisk);
    if (!Number.isFinite(hours) || hours <= 0) {
      setLocalError("SLA hours must be a positive number.");
      return;
    }
    if (!Number.isFinite(percent) || percent <= 0 || percent > 1) {
      setLocalError("At-risk percent must be between 0 and 1.");
      return;
    }
    if (!priority && !department && !category) {
      setLocalError("Pick at least one of priority, department, or category.");
      return;
    }
    setLocalError(null);
    void onSave({
      name: name.trim() || null,
      priority: priority || null,
      department: department || null,
      category: category || null,
      sla_hours: hours,
      at_risk_percent: percent,
      escalate_on_breach: escalate,
      active,
    });
  };

  return (
    <div className="grid gap-2 rounded-md border border-primary-100 bg-primary-50/40 p-3 sm:grid-cols-2 lg:grid-cols-4">
      <Input placeholder="Rule name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
      <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
        <option value="">Any priority</option>
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </Select>
      <Select value={department} onChange={(e) => setDepartment(e.target.value)}>
        <option value="">Any department</option>
        {DEPARTMENTS.map((d) => (
          <option key={d} value={d}>{d}</option>
        ))}
      </Select>
      <Select value={category} onChange={(e) => setCategory(e.target.value)}>
        <option value="">Any category</option>
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </Select>
      <Input
        type="number"
        min={1}
        value={slaHours}
        onChange={(e) => setSlaHours(e.target.value)}
        aria-label="SLA hours"
      />
      <Input
        type="number"
        min={0.01}
        max={1}
        step={0.05}
        value={atRisk}
        onChange={(e) => setAtRisk(e.target.value)}
        aria-label="At-risk percent"
      />
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={escalate} onChange={(e) => setEscalate(e.target.checked)} />
        Escalate breach
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active
      </label>
      {localError && <p className="sm:col-span-2 lg:col-span-4 text-sm text-danger-600">{localError}</p>}
      <div className="sm:col-span-2 lg:col-span-4 flex gap-2">
        <Button size="sm" onClick={submit} disabled={busy}>
          {busy ? "Saving…" : initial ? "Save" : "Create"}
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  );
}