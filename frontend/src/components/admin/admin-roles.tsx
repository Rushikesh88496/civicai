"use client";

import * as React from "react";
import { Plus, Loader2, ShieldCheck, Pencil } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminRoles,
  createAdminRole,
  updateAdminRole,
  type AdminRole,
} from "@/lib/admin-api";
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

const reserved = ["CITIZEN", "OFFICER", "ADMIN", "SUPER_ADMIN", "FIELD_WORKER", "WARD_REPRESENTATIVE"];

export function AdminRoles() {
  const [roles, setRoles] = React.useState<AdminRole[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editRole, setEditRole] = React.useState<AdminRole | null>(null);
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminRoles()
      .then((data) => {
        if (!active) return;
        setRoles(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load roles.");
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
      setEditRole(null);
      reload();
      return true;
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Operation failed.");
      return false;
    } finally {
      setMutating(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const name = String(form.get("name") || "").trim().toUpperCase();
    if (!name) {
      setFormError("Name is required.");
      return;
    }
    const description = (form.get("description") as string) || null;
    await runMutation(() => createAdminRole({ name, description }));
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editRole) return;
    const form = new FormData(e.currentTarget as HTMLFormElement);
    await runMutation(() =>
      updateAdminRole(editRole.id, {
        description: (form.get("description") as string) || null,
        is_active: form.get("is_active") === "true",
      })
    );
  };

  if (loading && roles.length === 0 && !error) {
    return <LoadingState message="Loading roles…" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Roles</h1>
          <p className="text-sm text-slate-500">Role catalog used for access control.</p>
        </div>
        <Button onClick={() => { setFormError(null); setCreateOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> Create Role
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-ai-600" /> Roles
          </CardTitle>
          <CardDescription>Reserved roles and their assigned user counts.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load roles" description={error} />}
          {!error && roles.length === 0 && !loading ? (
            <EmptyState title="No roles" description="No roles are configured yet." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Users</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {roles.map((role) => (
                  <TableRow key={role.id}>
                    <TableCell className="font-medium text-slate-900">{role.name}</TableCell>
                    <TableCell className="text-slate-600">{role.description || "—"}</TableCell>
                    <TableCell>{role.user_count}</TableCell>
                    <TableCell>
                      <Badge variant={role.is_active ? "success" : "destructive"}>
                        {role.is_active ? "Active" : "Disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={reserved.includes(role.name)}
                        onClick={() => { setFormError(null); setEditRole(role); }}
                        aria-label={`Edit ${role.name}`}
                      >
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

      <Modal open={createOpen} onClose={() => !mutating && setCreateOpen(false)} title="Create role">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="r-name">Name</Label>
            <Input id="r-name" name="name" placeholder="DEPARTMENT_DIRECTOR" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="r-desc">Description</Label>
            <Input id="r-desc" name="description" placeholder="What this role can do" />
          </div>
          {formError && <p className="text-sm text-danger-600">{formError}</p>}
          <Button type="submit" disabled={mutating} className="w-full">
            {mutating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Create role
          </Button>
        </form>
      </Modal>

      <Modal open={!!editRole} onClose={() => !mutating && setEditRole(null)} title="Edit role">
        {editRole && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="e-desc">Description</Label>
              <Input id="e-desc" name="description" defaultValue={editRole.description || ""} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="e-active">Status</Label>
              <Select id="e-active" name="is_active" defaultValue={String(editRole.is_active)}>
                <option value="true">Active</option>
                <option value="false">Disabled</option>
              </Select>
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