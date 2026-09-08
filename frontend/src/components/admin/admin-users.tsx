"use client";

import * as React from "react";
import { Plus, Search, Pencil, Ban, CheckCircle, Loader2, UsersIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminUsers,
  createAdminUser,
  updateAdminUser,
  disableAdminUser,
  enableAdminUser,
  fetchAdminRoles,
  fetchAdminWards,
  fetchAdminDepartments,
  type AdminUser,
  type AdminRole,
  type AdminWard,
  type AdminDepartment,
  type AdminUserCreate,
  type AdminUserUpdate,
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
import { formatDate } from "@/components/dashboard/format";

const roleOptions = ["CITIZEN", "OFFICER", "ADMIN", "SUPER_ADMIN", "FIELD_WORKER", "WARD_REPRESENTATIVE"];

interface Meta {
  roles: AdminRole[];
  wards: AdminWard[];
  departments: AdminDepartment[];
}

async function loadMeta(): Promise<Meta> {
  const [roles, wards, departments] = await Promise.all([
    fetchAdminRoles(),
    fetchAdminWards({ page_size: 200 }),
    fetchAdminDepartments({ page_size: 100 }),
  ]);
  return { roles, wards: wards.items, departments: departments.items };
}

function RoleBadge({ role }: { role: string }) {
  const variant =
    role === "SUPER_ADMIN"
      ? "default"
      : role === "ADMIN"
      ? "warning"
      : role === "OFFICER"
      ? "secondary"
      : role === "WARD_REPRESENTATIVE"
      ? "success"
      : "outline";
  return <Badge variant={variant}>{role}</Badge>;
}

export function AdminUsers() {
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [search, setSearch] = React.useState("");
  const [role, setRole] = React.useState("");
  const [activeFilter, setActiveFilter] = React.useState("");
  const [meta, setMeta] = React.useState<Meta | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);

  const [createOpen, setCreateOpen] = React.useState(false);
  const [editUser, setEditUser] = React.useState<AdminUser | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);

  const pageSize = 25;
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminUsers({
      page,
      page_size: pageSize,
      search: search || undefined,
      role: role || undefined,
      is_active: activeFilter ? activeFilter === "true" : undefined,
    })
      .then((data) => {
        if (!active) return;
        setUsers(data.items);
        setTotal(data.total);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load users.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, search, role, activeFilter, tick]);

  React.useEffect(() => {
    let active = true;
    loadMeta()
      .then((m) => active && setMeta(m))
      .catch(() => active && setMeta(null));
    return () => {
      active = false;
    };
  }, []);

  const runMutation = async (fn: () => Promise<unknown>) => {
    setMutating(true);
    setFormError(null);
    try {
      await fn();
      setCreateOpen(false);
      setEditUser(null);
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
    const payload: AdminUserCreate = {
      email: String(form.get("email") || ""),
      password: String(form.get("password") || ""),
      full_name: String(form.get("full_name") || ""),
      role: String(form.get("role") || "CITIZEN"),
      ward_code: (form.get("ward_code") as string) || null,
      department_code: (form.get("department_code") as string) || null,
      specialty: (form.get("specialty") as string) || null,
      rep_title: (form.get("rep_title") as string) || null,
    };
    if (!payload.email || !payload.full_name || !payload.password) {
      setFormError("Email, full name and a strong password are required.");
      return;
    }
    await runMutation(() => createAdminUser(payload));
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editUser) return;
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminUserUpdate = {
      full_name: (form.get("full_name") as string) || null,
      role: (form.get("role") as string) || null,
      ward_code: (form.get("ward_code") as string) || null,
      department_code: (form.get("department_code") as string) || null,
      specialty: (form.get("specialty") as string) || null,
      rep_title: (form.get("rep_title") as string) || null,
    };
    await runMutation(() => updateAdminUser(editUser.id, payload));
  };

  const handleToggleActive = async (user: AdminUser) => {
    await runMutation(() =>
      user.is_active ? disableAdminUser(user.id) : enableAdminUser(user.id)
    );
  };

  if (loading && users.length === 0 && !error) {
    return <LoadingState message="Loading users…" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Users</h1>
          <p className="text-sm text-slate-500">{total} accounts · create, edit, disable or restore access</p>
        </div>
        <Button onClick={() => { setFormError(null); setCreateOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> Create User
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UsersIcon className="h-5 w-5 text-ai-600" /> Accounts
          </CardTitle>
          <CardDescription>Search, filter and manage every user in the system.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_180px_180px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="pl-9"
                placeholder="Search by name or email…"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              />
            </div>
            <Select value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>
              <option value="">All roles</option>
              {roleOptions.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </Select>
            <Select value={activeFilter} onChange={(e) => { setActiveFilter(e.target.value); setPage(1); }}>
              <option value="">All status</option>
              <option value="true">Active</option>
              <option value="false">Disabled</option>
            </Select>
          </div>

          {error && <ErrorState title="Failed to load users" description={error} />}

          {!error && users.length === 0 && !loading ? (
            <EmptyState title="No users found" description="Try adjusting the filters or create a new user." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Ward</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell>
                        <div className="font-medium text-slate-900">{user.full_name}</div>
                        <div className="text-xs text-slate-500">{user.email}</div>
                      </TableCell>
                      <TableCell><RoleBadge role={user.role} /></TableCell>
                      <TableCell className="text-slate-600">{user.ward_code || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={user.is_active ? "success" : "destructive"}>
                          {user.is_active ? "Active" : "Disabled"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-slate-500">{formatDate(user.created_at)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditUser(user); }} aria-label={`Edit ${user.full_name}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleToggleActive(user)}
                            disabled={mutating}
                            aria-label={user.is_active ? `Disable ${user.full_name}` : `Enable ${user.full_name}`}
                          >
                            {user.is_active ? <Ban className="h-4 w-4 text-danger-500" /> : <CheckCircle className="h-4 w-4 text-success-600" />}
                          </Button>
                        </div>
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

      <Modal open={createOpen} onClose={() => !mutating && setCreateOpen(false)} title="Create user">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="u-email">Email</Label>
            <Input id="u-email" name="email" type="email" placeholder="user@example.com" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="u-name">Full name</Label>
            <Input id="u-name" name="full_name" placeholder="Full name" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="u-pass">Password (min 8, upper/lower/digit/symbol)</Label>
            <Input id="u-pass" name="password" type="password" placeholder="Strong password" required />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="u-role">Role</Label>
              <Select id="u-role" name="role" defaultValue="CITIZEN">
                {roleOptions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="u-ward">Ward</Label>
              <Select id="u-ward" name="ward_code" defaultValue="">
                <option value="">—</option>
                {meta?.wards.map((w) => (
                  <option key={w.id} value={w.code}>{w.code} · {w.name}</option>
                ))}
              </Select>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="u-dept">Department (field workers)</Label>
              <Select id="u-dept" name="department_code" defaultValue="">
                <option value="">—</option>
                {meta?.departments.map((d) => (
                  <option key={d.id} value={d.code}>{d.code} · {d.name}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="u-specialty">Specialty / Rep title</Label>
              <Input id="u-specialty" name="specialty" placeholder="Optional" />
            </div>
          </div>
          {formError && <p className="text-sm text-danger-600">{formError}</p>}
          <Button type="submit" disabled={mutating} className="w-full">
            {mutating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Create user
          </Button>
        </form>
      </Modal>

      <Modal open={!!editUser} onClose={() => !mutating && setEditUser(null)} title="Edit user">
        {editUser && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="e-name">Full name</Label>
              <Input id="e-name" name="full_name" defaultValue={editUser.full_name} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="e-role">Role</Label>
                <Select id="e-role" name="role" defaultValue={editUser.role}>
                  {roleOptions.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="e-ward">Ward</Label>
                <Select id="e-ward" name="ward_code" defaultValue={editUser.ward_code || ""}>
                  <option value="">—</option>
                  {meta?.wards.map((w) => (
                    <option key={w.id} value={w.code}>{w.code} · {w.name}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="e-dept">Department (field workers)</Label>
                <Select id="e-dept" name="department_code" defaultValue="">
                  <option value="">—</option>
                  {meta?.departments.map((d) => (
                    <option key={d.id} value={d.code}>{d.code} · {d.name}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="e-specialty">Specialty / Rep title</Label>
                <Input id="e-specialty" name="specialty" defaultValue={editUser.worker_status || ""} placeholder="Optional" />
              </div>
            </div>
            <p className={cn("text-xs text-slate-500")}>
              Current status: {editUser.is_active ? "Active" : "Disabled"} ·{" "}
              {editUser.is_email_verified ? "email verified" : "email unverified"}
            </p>
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