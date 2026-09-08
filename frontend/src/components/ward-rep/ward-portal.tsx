"use client";

import * as React from "react";
import {
  RefreshCw,
  MapPin,
  Activity,
  AlertTriangle,
  MessageSquare,
  Briefcase,
  GitBranch,
  Eye,
  Sparkles,
  Send,
  Inbox,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { useToast } from "@/components/ui/toast";
import { formatDate, formatDateTime, categoryLabel, statusLabel } from "@/components/dashboard/format";
import { WardMapView } from "@/components/ward-rep/ward-map";
import {
  fetchWardDashboard,
  fetchWardMap,
  fetchWardSummary,
  fetchConversation,
  fetchWorkOrder,
  fetchCluster,
  sendUpdate,
  requestEscalation,
  type WardDashboard,
  type WardMap,
  type WardSummary,
  type Conversation,
  type ThreadMessage,
  type WardWorkOrder,
  type Cluster,
  type WardMapComplaint,
} from "@/lib/ward-rep-api";

const PRIORITY_LABELS: Record<string, string> = {
  P1_CRITICAL: "P1 Critical",
  P2_HIGH: "P2 High",
  P3_MEDIUM: "P3 Medium",
  P4_LOW: "P4 Low",
};

function priorityBadge(priority?: string | null) {
  if (!priority) return null;
  const variant =
    priority === "P1_CRITICAL"
      ? "destructive"
      : priority === "P2_HIGH"
        ? "warning"
        : priority === "P3_MEDIUM"
          ? "secondary"
          : "success";
  return <Badge variant={variant}>{PRIORITY_LABELS[priority] ?? priority}</Badge>;
}

function statusBadge(status: string) {
  const lower = status.toLowerCase();
  const variant =
    lower.includes("resolved") || lower.includes("closed") || lower.includes("verified")
      ? "success"
      : lower.includes("escalated")
        ? "destructive"
        : lower.includes("open") || lower.includes("submitted") || lower.includes("analyzing")
          ? "warning"
          : "secondary";
  return <Badge variant={variant}>{statusLabel(status)}</Badge>;
}

function KpiCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "blue" | "red" | "orange" | "green" | "emerald" | "yellow";
}) {
  const toneClass =
    tone === "red"
      ? "text-danger-600"
      : tone === "orange"
        ? "text-warning-600"
        : tone === "green"
          ? "text-success-600"
          : tone === "emerald"
            ? "text-success-600"
            : tone === "yellow"
              ? "text-warning-600"
              : "text-slate-900";
  return (
    <Card className="p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={cn("mt-1 text-2xl font-bold", toneClass)}>{value}</div>
    </Card>
  );
}

export function WardPortal() {
  const [dashboard, setDashboard] = React.useState<WardDashboard | null>(null);
  const [mapData, setMapData] = React.useState<WardMap | null>(null);
  const [summary, setSummary] = React.useState<WardSummary | null>(null);

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [tick, setTick] = React.useState(0);

  // Action state
  const [active, setActive] = React.useState<WardMapComplaint | null>(null);
  const [modal, setModal] = React.useState<
    "incident" | "conversation" | "workorder" | "cluster" | "escalate" | null
  >(null);

  React.useEffect(() => {
    let activeFlag = true;
    Promise.all([fetchWardDashboard(), fetchWardMap(), fetchWardSummary()])
      .then(([d, m, s]) => {
        if (!activeFlag) return;
        setError(null);
        setDashboard(d);
        setMapData(m);
        setSummary(s);
      })
      .catch((err: unknown) => {
        if (!activeFlag) return;
        setError(err instanceof Error ? err.message : "Failed to load ward portal.");
      })
      .finally(() => {
        if (activeFlag) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => {
      activeFlag = false;
    };
  }, [tick]);

  // Light poll fallback for freshness.
  React.useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000);
    return () => clearInterval(id);
  }, []);

  const reload = React.useCallback(() => {
    setRefreshing(true);
    setTick((t) => t + 1);
  }, []);

  if (loading) return <LoadingState message="Loading ward portal…" />;

  if (error) {
    return (
      <ErrorState
        title="Unable to load ward portal"
        description={error}
        action={
          <Button variant="outline" onClick={reload}>
            Retry
          </Button>
        }
      />
    );
  }

  const ward = dashboard?.ward;
  const rep = dashboard?.representative ?? ward?.representative;
  const k = dashboard?.kpis;
  const complaints = mapData?.complaints ?? [];
  const summaryBadge =
    summary?.generated_by === "groq" ? (
      <Badge variant="success">Live · Groq</Badge>
    ) : (
      <Badge variant="outline">Synthesized</Badge>
    );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Ward {ward ? `${ward.code} · ${ward.name}` : "Representative Portal"}
          </h1>
          <p className="text-sm text-slate-500">
            {rep ? `Representative: ${rep.name ?? "—"}` : "Your ward"} — live complaints,
            priority map, and citizen conversations.
          </p>
        </div>
        <Button variant="outline" onClick={reload} disabled={refreshing}>
          <RefreshCw className={cn("mr-2 h-4 w-4", refreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Total Complaints" value={k?.total_complaints ?? 0} tone="blue" />
        <KpiCard label="Open" value={k?.open ?? 0} tone="orange" />
        <KpiCard label="Critical" value={k?.critical ?? 0} tone="red" />
        <KpiCard label="Resolved" value={k?.resolved ?? 0} tone="green" />
        <KpiCard
          label="SLA Breaches"
          value={k?.sla_breaches ?? 0}
          tone={(k?.sla_breaches ?? 0) > 0 ? "red" : "emerald"}
        />
      </div>

      {/* AI ward summary */}
      {summary && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-success-600" />
              AI Ward Summary
              {summaryBadge}
            </CardTitle>
            <CardDescription>
              Situation brief generated from your ward&apos;s records
              {summary.complaint_count ? ` (${summary.complaint_count} complaints).` : ""}
              {summary.generated_at ? ` Updated ${formatDateTime(summary.generated_at)}.` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm leading-relaxed text-slate-700">{summary.summary}</p>
            {summary.generated_by === "synthesized" && summary.highlights.length > 0 && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="mb-1 text-sm font-semibold text-slate-800">Highlights</div>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
                    {summary.highlights.map((h, i) => (
                      <li key={i}>{h}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="mb-1 text-sm font-semibold text-slate-800">Recommended actions</div>
                  <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
                    {summary.recommended_actions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
            {summary.generated_by === "groq" && (
              <p className="text-xs text-slate-400">
                Note: Groq is configured, so a live LLM produced this brief. Highlights/actions are
                embedded in the narrative for live mode.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Map + complaints */}
      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MapPin className="h-5 w-5 text-success-600" />
              Ward Incident Map
            </CardTitle>
            <CardDescription>
              Complaints coloured by dynamic priority (dots) and work orders (squares).
            </CardDescription>
          </CardHeader>
          <CardContent>
            {mapData && mapData.complaints.length === 0 ? (
              <div className="flex h-64 items-center justify-center">
                <EmptyState
                  icon={<MapPin className="h-8 w-8 text-slate-400" />}
                  title="No incidents in this ward"
                  description="When citizens report, their incidents will appear here."
                />
              </div>
            ) : mapData ? (
              <WardMapView data={mapData} />
            ) : (
              <div className="h-96 w-full bg-slate-100" />
            )}
          </CardContent>
        </Card>

        {/* Complaint list + actions */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-success-600" />
              Ward Complaints
            </CardTitle>
            <CardDescription>Review incidents and take action.</CardDescription>
          </CardHeader>
          <CardContent>
            {complaints.length === 0 ? (
              <EmptyState
                icon={<Inbox className="h-8 w-8 text-slate-400" />}
                title="No complaints"
                description="Your ward currently has no recorded complaints."
              />
            ) : (
              <div className="space-y-3">
                {complaints.map((c) => (
                  <ComplaintRow
                    key={c.id}
                    complaint={c}
                    onViewIncident={() => {
                      setActive(c);
                      setModal("incident");
                    }}
                    onConversation={() => {
                      setActive(c);
                      setModal("conversation");
                    }}
                    onWorkOrder={() => {
                      setActive(c);
                      setModal("workorder");
                    }}
                    onCluster={() => {
                      setActive(c);
                      setModal("cluster");
                    }}
                    onEscalate={() => {
                      setActive(c);
                      setModal("escalate");
                    }}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Modals */}
      <IncidentModal
        open={modal === "incident"}
        complaint={active}
        onClose={() => setModal(null)}
      />
      {active && (
        <ConversationModal
          key={`conv-${active.complaint_id}`}
          open={modal === "conversation"}
          complaintId={active.complaint_id}
          complaintTitle={active.title}
          onClose={() => setModal(null)}
        />
      )}
      {active && (
        <WorkOrderModal
          key={`wo-${active.complaint_id}`}
          open={modal === "workorder"}
          complaintId={active.complaint_id}
          complaintTitle={active.title}
          onClose={() => setModal(null)}
        />
      )}
      {active && (
        <ClusterModal
          key={`cluster-${active.complaint_id}`}
          open={modal === "cluster"}
          complaintId={active.complaint_id}
          complaintTitle={active.title}
          onClose={() => setModal(null)}
        />
      )}
      {active && (
        <EscalateModal
          key={`esc-${active.complaint_id}`}
          open={modal === "escalate"}
          complaint={active}
          onClose={() => setModal(null)}
          onDone={() => {
            setModal(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function ComplaintRow({
  complaint,
  onViewIncident,
  onConversation,
  onWorkOrder,
  onCluster,
  onEscalate,
}: {
  complaint: WardMapComplaint;
  onViewIncident: () => void;
  onConversation: () => void;
  onWorkOrder: () => void;
  onCluster: () => void;
  onEscalate: () => void;
}) {
  return (
    <div className="rounded-lg border border-border-soft p-3 transition-colors hover:bg-slate-50">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-slate-900">{complaint.title}</p>
            {priorityBadge(complaint.priority)}
            {statusBadge(complaint.status)}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {complaint.complaint_id} · {categoryLabel(complaint.category ?? "OTHER")}
            {complaint.department ? ` · ${complaint.department}` : ""} ·{" "}
            {formatDate(complaint.created_at)}
          </p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={onViewIncident}>
          <Eye className="mr-1 h-3.5 w-3.5" /> View
        </Button>
        <Button size="sm" variant="outline" onClick={onConversation}>
          <MessageSquare className="mr-1 h-3.5 w-3.5" /> Chat
        </Button>
        <Button size="sm" variant="outline" onClick={onWorkOrder}>
          <Briefcase className="mr-1 h-3.5 w-3.5" /> Work Order
        </Button>
        <Button size="sm" variant="outline" onClick={onCluster}>
          <GitBranch className="mr-1 h-3.5 w-3.5" /> Cluster
        </Button>
        <Button size="sm" variant="outline" onClick={onEscalate}>
          <AlertTriangle className="mr-1 h-3.5 w-3.5" /> Escalate
        </Button>
      </div>
    </div>
  );
}

function IncidentModal({
  open,
  complaint,
  onClose,
}: {
  open: boolean;
  complaint: WardMapComplaint | null;
  onClose: () => void;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Incident Details">
      {complaint && (
        <div className="space-y-3 text-sm">
          <div>
            <div className="font-semibold text-slate-900">{complaint.title}</div>
            <div className="mt-1 flex flex-wrap gap-2">
              {priorityBadge(complaint.priority)}
              {statusBadge(complaint.status)}
              <Badge variant="secondary">{categoryLabel(complaint.category ?? "OTHER")}</Badge>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-slate-600">
            <div>ID: {complaint.complaint_id}</div>
            <div>Dept: {complaint.department ?? "—"}</div>
            <div>Reported: {formatDateTime(complaint.created_at)}</div>
            <div>Priority: {complaint.priority ?? "—"}</div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm">
              <MessageSquare className="mr-1 h-3.5 w-3.5" /> Chat
            </Button>
            <Button variant="outline" size="sm">
              <GitBranch className="mr-1 h-3.5 w-3.5" /> Cluster
            </Button>
            <Button variant="outline" size="sm">
              <Briefcase className="mr-1 h-3.5 w-3.5" /> Work Order
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function ConversationModal({
  open,
  complaintId,
  complaintTitle,
  onClose,
}: {
  open: boolean;
  complaintId: string;
  complaintTitle: string;
  onClose: () => void;
}) {
  const { addToast } = useToast();
  const [conv, setConv] = React.useState<Conversation | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    let activeFlag = true;
    fetchConversation(complaintId)
      .then((c) => {
        if (activeFlag) setConv(c);
      })
      .catch((err: unknown) => {
        if (activeFlag) addToast(err instanceof Error ? err.message : "Failed to load thread.", "error");
      })
      .finally(() => {
        if (activeFlag) setLoading(false);
      });
    return () => {
      activeFlag = false;
    };
  }, [open, complaintId, addToast]);

  const handleSend = () => {
    if (!draft.trim()) {
      addToast("Message cannot be empty.", "error");
      return;
    }
    setSending(true);
    sendUpdate(complaintId, draft.trim())
      .then((c) => {
        setConv(c);
        setDraft("");
        addToast("Update sent to the citizen.", "success");
      })
      .catch((err: unknown) => {
        addToast(err instanceof Error ? err.message : "Failed to send update.", "error");
      })
      .finally(() => setSending(false));
  };

  return (
    <Modal open={open} onClose={onClose} title={`Conversation · ${complaintTitle}`}>
      <div className="max-h-72 space-y-3 overflow-y-auto pr-1">
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading thread…
          </div>
        ) : !conv || conv.messages.length === 0 ? (
          <p className="text-sm text-slate-500">No messages yet. Send the citizen an update.</p>
        ) : (
          conv.messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>
      <div className="mt-4 space-y-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Write an update for the citizen…"
          rows={3}
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button onClick={handleSend} disabled={sending}>
            {sending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />}
            Send Update
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function MessageBubble({ message }: { message: ThreadMessage }) {
  const staff = message.role !== "CITIZEN";
  return (
    <div className={cn("flex", staff ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm",
          staff ? "bg-success-600 text-white" : "bg-slate-100 text-slate-800"
        )}
      >
        <div className={cn("mb-0.5 text-xs font-medium", staff ? "text-success-100" : "text-slate-500")}>
          {message.author_name ?? message.role} · {formatDateTime(message.created_at)}
        </div>
        <div className="whitespace-pre-wrap">{message.body}</div>
      </div>
    </div>
  );
}

function WorkOrderModal({
  open,
  complaintId,
  complaintTitle,
  onClose,
}: {
  open: boolean;
  complaintId: string;
  complaintTitle: string;
  onClose: () => void;
}) {
  const { addToast } = useToast();
  const [wo, setWo] = React.useState<WardWorkOrder | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    let activeFlag = true;
    fetchWorkOrder(complaintId)
      .then((w) => {
        if (activeFlag) setWo(w);
      })
      .catch((err: unknown) => {
        if (activeFlag) addToast(err instanceof Error ? err.message : "Failed to load work order.", "error");
      })
      .finally(() => {
        if (activeFlag) setLoading(false);
      });
    return () => {
      activeFlag = false;
    };
  }, [open, complaintId, addToast]);

  return (
    <Modal open={open} onClose={onClose} title={`Work Order · ${complaintTitle}`}>
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : !wo ? (
        <p className="text-sm text-slate-500">
          No work order has been created for this complaint yet.
        </p>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">{wo.department}</span>
            {statusBadge(wo.status)}
            {priorityBadge(wo.priority)}
          </div>
          <div className="grid grid-cols-2 gap-2 text-slate-600">
            <div>Worker: {wo.worker_name ?? "Not assigned"}</div>
            <div>ETA: {wo.eta_minutes != null ? `${wo.eta_minutes} min` : "—"}</div>
            <div>Due: {wo.due_at ? formatDate(wo.due_at) : "—"}</div>
            <div>ID: {wo.id}</div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function ClusterModal({
  open,
  complaintId,
  complaintTitle,
  onClose,
}: {
  open: boolean;
  complaintId: string;
  complaintTitle: string;
  onClose: () => void;
}) {
  const { addToast } = useToast();
  const [cluster, setCluster] = React.useState<Cluster | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    let activeFlag = true;
    fetchCluster(complaintId)
      .then((c) => {
        if (activeFlag) setCluster(c);
      })
      .catch((err: unknown) => {
        if (activeFlag) addToast(err instanceof Error ? err.message : "Failed to load cluster.", "error");
      })
      .finally(() => {
        if (activeFlag) setLoading(false);
      });
    return () => {
      activeFlag = false;
    };
  }, [open, complaintId, addToast]);

  return (
    <Modal open={open} onClose={onClose} title={`Complaint Cluster · ${complaintTitle}`}>
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : !cluster || cluster.members.length === 0 ? (
        <p className="text-sm text-slate-500">
          No related (duplicate) complaints were found for this incident.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            <span className="font-medium text-slate-900">{cluster.members.length}</span> related{" "}
            {cluster.members.length === 1 ? "complaint" : "complaints"} found.
          </p>
          <ul className="space-y-2">
            {cluster.members.map((m) => (
              <li key={m.id} className="rounded-lg border border-border-soft p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900">{m.title}</span>
                  {priorityBadge(m.priority)}
                  {statusBadge(m.status)}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  <Badge variant="outline">
                    {m.correlation_status === "CONFIRMED_DUPLICATE" ? "Confirmed duplicate" : "Possible duplicate"}
                  </Badge>
                  {m.similarity != null && <span> · similarity {Math.round(m.similarity * 100)}%</span>}
                  {m.distance_m != null && <span> · {Math.round(m.distance_m)} m away</span>}
                  <span> · {formatDate(m.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}

function EscalateModal({
  open,
  complaint,
  onClose,
  onDone,
}: {
  open: boolean;
  complaint: WardMapComplaint | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const { addToast } = useToast();
  const [reason, setReason] = React.useState("");
  const [sending, setSending] = React.useState(false);

  const handleEscalate = () => {
    if (!complaint) return;
    if (!reason.trim()) {
      addToast("Please provide a reason for escalation.", "error");
      return;
    }
    setSending(true);
    requestEscalation(complaint.complaint_id, reason.trim())
      .then(() => {
        addToast("Complaint escalated.", "success");
        onDone();
      })
      .catch((err: unknown) => {
        addToast(err instanceof Error ? err.message : "Failed to escalate.", "error");
      })
      .finally(() => setSending(false));
  };

  return (
    <Modal open={open} onClose={onClose} title={`Escalate · ${complaint?.title ?? ""}`}>
      <p className="mb-3 text-sm text-slate-600">
        Escalating marks this complaint as needing urgent upper-level attention.
      </p>
      <Textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason for escalation…"
        rows={4}
      />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={handleEscalate} disabled={sending}>
          {sending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <AlertTriangle className="mr-1 h-4 w-4" />}
          Escalate
        </Button>
      </div>
    </Modal>
  );
}
