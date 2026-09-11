"use client";

import * as React from "react";
import { Plus, Pencil, Trash2, Clock3, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminSlaPolicies,
  createAdminSlaPolicy,
  updateAdminSlaPolicy,
  deleteAdminSlaPolicy,
} from "@/lib/admin-api";
import type { SlaPolicy, SlaPolicyIn } from "@/lib/officer-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Modal } from "@/components/ui/modal";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";

function SlaPolicyForm({
  initial,
  error,
  mutating,
  onSubmit,
}: {
  initial?: SlaPolicy;
  error: string | null;
  mutating: boolean;
  onSubmit: (e: React.FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="sla-name">Name</Label>
        <Input id="sla-name" name="name" defaultValue={initial?.name || ""} placeholder="Critical Priority SLA" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="sla-priority">Priority</Label>
          <Input id="sla-priority" name="priority" defaultValue={initial?.priority || ""} placeholder="critical / high / medium" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="sla-category">Category</Label>
          <Input id="sla-category" name="category" defaultValue={initial?.category || ""} placeholder="e.g. ROADS, WATER" />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="sla-dept">Department</Label>
          <Input id="sla-dept" name="department" defaultValue={initial?.department || ""} placeholder="e.g. SANITATION" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="sla-hours">SLA hours</Label>
          <Input id="sla-hours" name="sla_hours" type="number" min="1" defaultValue={initial?.sla_hours || 48} required />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="sla-risk">At-risk threshold %</Label>
          <Input id="sla-risk" name="at_risk_percent" type="number" min="1" max="100" defaultValue={initial?.at_risk_percent ?? 75} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="sla-esc">Escalate on breach</Label>
          <Select id="sla-esc" name="escalate_on_breach" defaultValue={String(initial?.escalate_on_breach ?? true)}>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </Select>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="sla-active">Active</Label>
        <Select id="sla-active" name="active" defaultValue={String(initial?.active ?? true)}>
          <option value="true">Active</option>
          <option value="false">Draft / Inactive</option>
        </Select>
      </div>
      {error && <p className="text-sm text-danger-600">{error}</p>}
      <Button type="submit" disabled={mutating} className="w-full">
        {mutating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {initial ? "Save changes" : "Create policy"}
      </Button>
    </form>
  );
}

export function AdminSla() {
  const [policies, setPolicies] = React.useState<SlaPolicy[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editPolicy, setEditPolicy] = React.useState<SlaPolicy | null>(null);
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminSlaPolicies()
      .then((data) => {
        if (!active) return;
        setPolicies(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load SLA policies.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const buildPayload = (form: FormData): SlaPolicyIn => ({
    name: (form.get("name") as string) || null,
    priority: (form.get("priority") as string) || null,
    department: (form.get("department") as string) || null,
    category: (form.get("category") as string) || null,
    sla_hours: Number(form.get("sla_hours") || 0),
    at_risk_percent: Number(form.get("at_risk_percent") || 75),
    escalate_on_breach: form.get("escalate_on_breach") === "true",
    active: form.get("active") === "true",
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload = buildPayload(form);
    if (!payload.sla_hours || payload.sla_hours <= 0) {
      setFormError("SLA hours must be greater than 0.");
      return;
    }
    setMutating(true);
    setFormError(null);
    try {
      await createAdminSlaPolicy(payload);
      setCreateOpen(false);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Create failed.");
    } finally {
      setMutating(false);
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editPolicy) return;
    const form = new FormData(e.currentTarget as HTMLFormElement);
    setMutating(true);
    setFormError(null);
    try {
      await updateAdminSlaPolicy(editPolicy.id, buildPayload(form));
      setEditPolicy(null);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Update failed.");
    } finally {
      setMutating(false);
    }
  };

  const handleDelete = async (policy: SlaPolicy) => {
    if (!confirm(`Delete SLA policy "${policy.name || policy.id}"?`)) return;
    setMutating(true);
    try {
      await deleteAdminSlaPolicy(policy.id);
      reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setMutating(false);
    }
  };

  if (loading && policies.length === 0 && !error) {
    return <LoadingState message="Loading SLA policies…" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">SLA Policies</h1>
          <p className="text-sm text-slate-500">{policies.length} policies</p>
        </div>
        <Button onClick={() => { setFormError(null); setCreateOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> Create Policy
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock3 className="h-5 w-5 text-ai-600" /> Service Level Agreements
          </CardTitle>
          <CardDescription>Define response deadlines and at-risk thresholds for complaint categories.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load SLA policies" description={error} />}
          {!error && policies.length === 0 && !loading ? (
            <EmptyState title="No SLA policies" description="Create an SLA policy to set response deadlines." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>SLA hours</TableHead>
                  <TableHead>At-risk %</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {policies.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium text-slate-900">{p.name || "—"}</TableCell>
                    <TableCell className="text-slate-600">{p.priority || "—"}</TableCell>
                    <TableCell className="text-slate-600">{p.category || "—"}</TableCell>
                    <TableCell>{p.sla_hours}h</TableCell>
                    <TableCell>{p.at_risk_percent}%</TableCell>
                    <TableCell>
                      <Badge variant={p.active ? "success" : "secondary"}>
                        {p.active ? "Active" : "Draft"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditPolicy(p); }} aria-label="Edit policy">
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDelete(p)} disabled={mutating} aria-label="Delete policy">
                          <Trash2 className="h-4 w-4 text-danger-500" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal open={createOpen} onClose={() => !mutating && setCreateOpen(false)} title="Create SLA policy">
        <SlaPolicyForm error={formError} mutating={mutating} onSubmit={handleCreate} />
      </Modal>

      <Modal open={!!editPolicy} onClose={() => !mutating && setEditPolicy(null)} title="Edit SLA policy">
        {editPolicy && <SlaPolicyForm initial={editPolicy} error={formError} mutating={mutating} onSubmit={handleUpdate} />}
      </Modal>
    </div>
  );
}