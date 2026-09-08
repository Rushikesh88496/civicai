"use client";

import * as React from "react";
import { Plus, Pencil, Tag, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminComplaintCategories,
  createAdminComplaintCategory,
  updateAdminComplaintCategory,
  type AdminComplaintCategory,
  type AdminComplaintCategoryIn,
  type AdminComplaintCategoryUpdate,
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
import { formatDate } from "@/components/dashboard/format";

export function AdminComplaintCategories() {
  const [categories, setCategories] = React.useState<AdminComplaintCategory[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editCat, setEditCat] = React.useState<AdminComplaintCategory | null>(null);
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminComplaintCategories()
      .then((data) => {
        if (!active) return;
        setCategories(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load categories.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const runMutation = async (fn: () => Promise<unknown>) => {
    setMutating(true);
    setFormError(null);
    try {
      await fn();
      setCreateOpen(false);
      setEditCat(null);
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
    const payload: AdminComplaintCategoryIn = {
      code: String(form.get("code") || "").trim(),
      label: String(form.get("label") || "").trim(),
      description: (form.get("description") as string) || null,
      sort_order: form.get("sort_order") ? Number(form.get("sort_order")) : 0,
    };
    if (!payload.code || !payload.label) {
      setFormError("Code and label are required.");
      return;
    }
    await runMutation(() => createAdminComplaintCategory(payload));
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editCat) return;
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminComplaintCategoryUpdate = {
      label: (form.get("label") as string) || null,
      description: (form.get("description") as string) || null,
      sort_order: form.get("sort_order") !== null && form.get("sort_order") !== undefined && form.get("sort_order") !== "" ? Number(form.get("sort_order")) : null,
      is_active: form.get("is_active") === "true",
    };
    await runMutation(() => updateAdminComplaintCategory(editCat.id, payload));
  };

  if (loading && categories.length === 0 && !error) {
    return <LoadingState message="Loading categories…" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Complaint Categories</h1>
          <p className="text-sm text-slate-500">{categories.length} categories</p>
        </div>
        <Button onClick={() => { setFormError(null); setCreateOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> Create Category
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Tag className="h-5 w-5 text-ai-600" /> Categories
          </CardTitle>
          <CardDescription>Classifies complaints for routing, priority and SLA assignment.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load categories" description={error} />}
          {!error && categories.length === 0 && !loading ? (
            <EmptyState title="No categories" description="Create a category to classify incoming complaints." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Label</TableHead>
                  <TableHead>Sort</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {categories.map((cat) => (
                  <TableRow key={cat.id}>
                    <TableCell className="font-mono text-sm text-slate-900">{cat.code}</TableCell>
                    <TableCell className="font-medium text-slate-900">{cat.label}</TableCell>
                    <TableCell className="text-slate-600">{cat.sort_order}</TableCell>
                    <TableCell>
                      <Badge variant={cat.is_active ? "success" : "destructive"}>
                        {cat.is_active ? "Active" : "Disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-slate-500">{formatDate(cat.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditCat(cat); }} aria-label={`Edit ${cat.label}`}>
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

      <Modal open={createOpen} onClose={() => !mutating && setCreateOpen(false)} title="Create category">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="c-code">Code</Label>
            <Input id="c-code" name="code" placeholder="ROAD_REPAIR" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-label">Label</Label>
            <Input id="c-label" name="label" placeholder="Road Repair" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-desc">Description</Label>
            <Input id="c-desc" name="description" placeholder="Optional" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-sort">Sort order</Label>
            <Input id="c-sort" name="sort_order" type="number" defaultValue={0} />
          </div>
          {formError && <p className="text-sm text-danger-600">{formError}</p>}
          <Button type="submit" disabled={mutating} className="w-full">
            {mutating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Create category
          </Button>
        </form>
      </Modal>

      <Modal open={!!editCat} onClose={() => !mutating && setEditCat(null)} title="Edit category">
        {editCat && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="e-label">Label</Label>
              <Input id="e-label" name="label" defaultValue={editCat.label} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="e-desc">Description</Label>
              <Input id="e-desc" name="description" defaultValue={editCat.description || ""} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="e-sort">Sort order</Label>
                <Input id="e-sort" name="sort_order" type="number" defaultValue={editCat.sort_order} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="e-active">Status</Label>
                <select id="e-active" name="is_active" defaultValue={String(editCat.is_active)} className="flex h-10 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm">
                  <option value="true">Active</option>
                  <option value="false">Disabled</option>
                </select>
              </div>
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