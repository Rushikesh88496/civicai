"use client";

import * as React from "react";
import { Pencil, Scale, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminPriorityWeights,
  updateAdminPriorityWeight,
  type AdminPriorityWeight,
  type AdminPriorityWeightUpdate,
} from "@/lib/admin-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Modal } from "@/components/ui/modal";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";

export function AdminPriorityWeights() {
  const [weights, setWeights] = React.useState<AdminPriorityWeight[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [editWeight, setEditWeight] = React.useState<AdminPriorityWeight | null>(null);
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminPriorityWeights()
      .then((data) => {
        if (!active) return;
        setWeights(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load priority weights.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editWeight) return;
    setMutating(true);
    setFormError(null);
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminPriorityWeightUpdate = {
      label: (form.get("label") as string) || null,
      weight: form.get("weight") !== null && form.get("weight") !== undefined && form.get("weight") !== "" ? Number(form.get("weight")) : null,
      is_active: form.get("is_active") === "true",
    };
    if (payload.weight !== null && payload.weight !== undefined && (payload.weight < 0 || payload.weight > 1)) {
      setFormError("Weight must be between 0 and 1.");
      setMutating(false);
      return;
    }
    try {
      await updateAdminPriorityWeight(editWeight.id, payload);
      setEditWeight(null);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Update failed.");
    } finally {
      setMutating(false);
    }
  };

  if (loading && weights.length === 0 && !error) {
    return <LoadingState message="Loading priority weights…" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Priority Weights</h1>
        <p className="text-sm text-slate-500">{weights.length} factors · all 6 required, edit only</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Scale className="h-5 w-5 text-ai-600" /> Priority Factors
          </CardTitle>
          <CardDescription>Weighted factors (0.0–1.0) used in complaint scoring.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load priority weights" description={error} />}
          {!error && weights.length === 0 && !loading ? (
            <EmptyState title="No weights configured" description="Seed the database to populate default weights." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead>Label</TableHead>
                  <TableHead>Weight</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {weights.map((w) => (
                  <TableRow key={w.id}>
                    <TableCell className="font-mono text-sm text-slate-900">{w.key}</TableCell>
                    <TableCell className="font-medium text-slate-900">{w.label}</TableCell>
                    <TableCell className="text-slate-600">{w.weight.toFixed(2)}</TableCell>
                    <TableCell>
                      <Badge variant={w.is_active ? "success" : "destructive"}>
                        {w.is_active ? "Active" : "Disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditWeight(w); }} aria-label={`Edit ${w.label}`}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal open={!!editWeight} onClose={() => !mutating && setEditWeight(null)} title="Edit priority weight">
        {editWeight && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label>Key</Label>
              <p className="rounded-lg border border-border-soft bg-slate-50 px-3 py-2 text-sm font-mono text-slate-700">{editWeight.key}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pw-label">Label</Label>
              <Input id="pw-label" name="label" defaultValue={editWeight.label} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pw-weight">Weight (0.0 – 1.0)</Label>
              <Input id="pw-weight" name="weight" type="number" step="0.01" min="0" max="1" defaultValue={editWeight.weight} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pw-active">Status</Label>
              <select id="pw-active" name="is_active" defaultValue={String(editWeight.is_active)} className="flex h-10 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm">
                <option value="true">Active</option>
                <option value="false">Disabled</option>
              </select>
            </div>
            {formError && <p className="text-sm text-danger-600">{formError}</p>}
            <Button type="submit" disabled={mutating} className="w-full">
              {mutating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Save changes
            </Button>
          </form>
        )}
      </Modal>
    </div>
  );
}