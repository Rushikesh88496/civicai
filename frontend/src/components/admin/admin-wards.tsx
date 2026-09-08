"use client";

import * as React from "react";
import { Plus, Pencil, MapPin, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminWards,
  createAdminWard,
  updateAdminWard,
  type AdminWard,
  type AdminWardIn,
  type AdminWardUpdate,
} from "@/lib/admin-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { formatDate } from "@/components/dashboard/format";

export function AdminWards() {
  const [wards, setWards] = React.useState<AdminWard[]>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editWard, setEditWard] = React.useState<AdminWard | null>(null);
  const pageSize = 25;
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminWards({ page, page_size: pageSize })
      .then((data) => {
        if (!active) return;
        setWards(data.items);
        setTotal(data.total);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load wards.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, tick]);

  const runMutation = async (fn: () => Promise<unknown>) => {
    setMutating(true);
    setFormError(null);
    try {
      await fn();
      setCreateOpen(false);
      setEditWard(null);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Operation failed.");
    } finally {
      setMutating(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminWardIn = {
      name: String(form.get("name") || "").trim(),
      code: String(form.get("code") || "").trim(),
      description: (form.get("description") as string) || null,
    };
    if (!payload.name || !payload.code) {
      setFormError("Name and code are required.");
      return;
    }
    await runMutation(() => createAdminWard(payload));
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editWard) return;
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminWardUpdate = {
      name: (form.get("name") as string) || null,
      description: (form.get("description") as string) || null,
      is_active: form.get("is_active") === "true",
    };
    await runMutation(() => updateAdminWard(editWard.id, payload));
  };

  if (loading && wards.length === 0 && !error) {
    return <LoadingState message="Loading wards…" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Wards</h1>
          <p className="text-sm text-slate-500">{total} wards</p>
        </div>
        <Button onClick={() => { setFormError(null); setCreateOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> Create Ward
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapPin className="h-5 w-5 text-ai-600" /> Wards
          </CardTitle>
          <CardDescription>Geographic zones for complaints and field assignment.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load wards" description={error} />}
          {!error && wards.length === 0 && !loading ? (
            <EmptyState title="No wards" description="Create a ward to begin geo-routing complaints." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {wards.map((ward) => (
                    <TableRow key={ward.id}>
                      <TableCell className="font-mono text-sm text-slate-900">{ward.code}</TableCell>
                      <TableCell className="font-medium text-slate-900">{ward.name}</TableCell>
                      <TableCell className="text-slate-600">{ward.description || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={ward.is_active ? "success" : "destructive"}>
                          {ward.is_active ? "Active" : "Disabled"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-slate-500">{formatDate(ward.created_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditWard(ward); }} aria-label={`Edit ${ward.name}`}>
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

      <Modal open={createOpen} onClose={() => !mutating && setCreateOpen(false)} title="Create ward">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="w-code">Code</Label>
            <Input id="w-code" name="code" placeholder="WARD_A01" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="w-name">Name</Label>
            <Input id="w-name" name="name" placeholder="Ward name" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="w-desc">Description</Label>
            <Input id="w-desc" name="description" placeholder="Optional" />
          </div>
          {formError && <p className="text-sm text-danger-600">{formError}</p>}
          <Button type="submit" disabled={mutating} className="w-full">
            {mutating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Create ward
          </Button>
        </form>
      </Modal>

      <Modal open={!!editWard} onClose={() => !mutating && setEditWard(null)} title="Edit ward">
        {editWard && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="e-name">Name</Label>
              <Input id="e-name" name="name" defaultValue={editWard.name} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="e-desc">Description</Label>
              <Input id="e-desc" name="description" defaultValue={editWard.description || ""} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="e-active">Status</Label>
              <select id="e-active" name="is_active" defaultValue={String(editWard.is_active)} className="flex h-10 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm">
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