"use client";

import * as React from "react";
import { Pencil, Landmark, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import {
  fetchAdminRepresentatives,
  updateAdminRepresentative,
  fetchAdminWards,
  type AdminRepresentative,
  type AdminRepresentativeUpdate,
  type AdminWard,
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

const statusOptions = ["active", "inactive", "suspended"];

export function AdminRepresentatives() {
  const [reps, setReps] = React.useState<AdminRepresentative[]>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [mutating, setMutating] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [editRep, setEditRep] = React.useState<AdminRepresentative | null>(null);
  const [wards, setWards] = React.useState<AdminWard[]>([]);
  const pageSize = 25;
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchAdminRepresentatives({ page, page_size: pageSize })
      .then((data) => {
        if (!active) return;
        setReps(data.items);
        setTotal(data.total);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load representatives.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, tick]);

  React.useEffect(() => {
    fetchAdminWards({ page_size: 200 }).then((d) => setWards(d.items)).catch(() => {});
  }, []);

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editRep) return;
    setMutating(true);
    setFormError(null);
    const form = new FormData(e.currentTarget as HTMLFormElement);
    const payload: AdminRepresentativeUpdate = {
      ward_code: (form.get("ward_code") as string) || null,
      title: (form.get("title") as string) || null,
      status: (form.get("status") as string) || null,
    };
    try {
      await updateAdminRepresentative(editRep.id, payload);
      setEditRep(null);
      reload();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Update failed.");
    } finally {
      setMutating(false);
    }
  };

  if (loading && reps.length === 0 && !error) {
    return <LoadingState message="Loading representatives…" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Ward Representatives</h1>
        <p className="text-sm text-slate-500">{total} representatives · assigned to wards</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Landmark className="h-5 w-5 text-ai-600" /> Ward Representatives
          </CardTitle>
          <CardDescription>Citizens who represent and escalate issues within their ward.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && <ErrorState title="Failed to load representatives" description={error} />}
          {!error && reps.length === 0 && !loading ? (
            <EmptyState title="No representatives" description="No ward representatives have been registered yet." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Representative</TableHead>
                    <TableHead>Ward</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reps.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>
                        <div className="font-medium text-slate-900">{r.full_name}</div>
                        <div className="text-xs text-slate-500">{r.email}</div>
                      </TableCell>
                      <TableCell className="text-slate-600">{r.ward_name || r.ward_code || "—"}</TableCell>
                      <TableCell className="text-slate-600">{r.title || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={r.status === "active" ? "success" : "secondary"}>{r.status}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" onClick={() => { setFormError(null); setEditRep(r); }} aria-label={`Edit ${r.full_name}`}>
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

      <Modal open={!!editRep} onClose={() => !mutating && setEditRep(null)} title="Edit representative">
        {editRep && (
          <form onSubmit={handleUpdate} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="rep-ward">Ward</Label>
              <Select id="rep-ward" name="ward_code" defaultValue={editRep.ward_code || ""}>
                <option value="">—</option>
                {wards.map((w) => (
                  <option key={w.id} value={w.code}>{w.code} · {w.name}</option>
                ))}
              </Select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="rep-title">Title</Label>
                <Input id="rep-title" name="title" defaultValue={editRep.title || ""} placeholder="Ward President" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rep-status">Status</Label>
                <Select id="rep-status" name="status" defaultValue={editRep.status}>
                  {statusOptions.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </Select>
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