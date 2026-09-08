"use client";

import * as React from "react";
import { Pencil, HardHat, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminFieldWorkers,
  updateAdminFieldWorker,
  fetchAdminDepartments,
  type AdminFieldWorker,
  type AdminFieldWorkerUpdate,
  type AdminDepartment,
} from "@/lib/admin-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";

const statusOptions = ["available", "busy", "on_leave", "offline"];

export function AdminFieldWorkers() {
  const [workers, setWorkers] = React.useState<AdminFieldWorker[]>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [editWorker, setEditWorker] = React.useState<AdminFieldWorker | null>(null);
  const [departments, setDepartments] = React.useState<AdminDepartment[]>([]);
  const pageSize = 25;
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminFieldWorkers({ page, page_size: pageSize })
      .then((data) => {
        if (!active) return;
        setWorkers(data.items);
        setTotal(data.total);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load field workers.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, tick]);

  React.useEffect(() => {
    fetchAdminDepartments({ page_size: 100 })
      .then((d) => setDepartments(d.items))
      .catch(() => {});
  }, []);

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editWorker) return;
    setMutating(true);
    setFormError(null);
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminFieldWorkerUpdate = {
      department_code: (form.get("department_code") as string) || null,
      specialty: (form.get("specialty") as string) || null,
      status: (form.get("status") as string) || null,
      skill_tags: ((form.get("skill_tags") as string) || "").split(",").map((s) => s.trim()).filter(Boolean),
      equipment: ((form.get("equipment") as string) || "").split(",").map((s) => s.trim()).filter(Boolean),
      max_active_orders: form.get("max_active_orders") ? Number(form.get("max_active_orders")) : null,
    };
    try {
      await updateAdminFieldWorker(editWorker.id, payload);
      setEditWorker(null);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Update failed.");
    } finally {
      setMutating(false);
    }
  };

  if (loading && workers.length === 0 && !error) {
    return <LoadingState message="Loading field workers…" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Field Workers</h1>
        <p className="text-sm text-slate-500">{total} field workers · manage departments, status and skills</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardHat className="h-5 w-5 text-ai-600" /> Field Workers
          </CardTitle>
          <CardDescription>Deployed workers who pick up and resolve citizen complaints.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load field workers" description={error} />}
          {!error && workers.length === 0 && !loading ? (
            <EmptyState title="No field workers" description="No field workers have been registered yet." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Worker</TableHead>
                    <TableHead>Department</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Specialty</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workers.map((w) => (
                    <TableRow key={w.id}>
                      <TableCell>
                        <div className="font-medium text-slate-900">{w.full_name}</div>
                        <div className="text-xs text-slate-500">{w.email}</div>
                      </TableCell>
                      <TableCell className="text-slate-600">{w.department_name || w.department_code || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={w.status === "available" ? "success" : w.status === "busy" ? "warning" : "secondary"}>
                          {w.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-slate-600">{w.specialty || "—"}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditWorker(w); }} aria-label={`Edit ${w.full_name}`}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Pagination currentPage={page} totalPages={Math.max(1, Math.ceil(total / pageSize))} onPageChange={setPage} />
            </>
          )}
        </CardContent>
      </Card>

      <Modal open={!!editWorker} onClose={() => !mutating && setEditWorker(null)} title="Edit field worker">
        {editWorker && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="fw-dept">Department</Label>
              <Select id="fw-dept" name="department_code" defaultValue={editWorker.department_code || ""}>
                <option value="">—</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.code}>{d.code} · {d.name}</option>
                ))}
              </Select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="fw-specialty">Specialty</Label>
                <Input id="fw-specialty" name="specialty" defaultValue={editWorker.specialty || ""} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="fw-status">Status</Label>
                <Select id="fw-status" name="status" defaultValue={editWorker.status}>
                  {statusOptions.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fw-skills">Skill tags (comma-separated)</Label>
              <Input id="fw-skills" name="skill_tags" defaultValue={editWorker.skill_tags?.join(", ") || ""} placeholder="plumbing, emergency" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fw-equip">Equipment (comma-separated)</Label>
              <Input id="fw-equip" name="equipment" defaultValue={editWorker.equipment?.join(", ") || ""} placeholder="van, toolkit" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fw-max">Max active orders</Label>
              <Input id="fw-max" name="max_active_orders" type="number" defaultValue={editWorker.max_active_orders ?? ""} />
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