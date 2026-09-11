"use client";

import * as React from "react";
import { ScrollText } from "lucide-react";
import { ApiError } from "@/lib/auth-api";
import { fetchAdminAuditLogs, type AuditLog } from "@/lib/admin-api";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Pagination } from "@/components/ui/pagination";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { formatDateTime } from "@/components/dashboard/format";

const actionColors: Record<string, "default" | "success" | "warning" | "destructive" | "secondary"> = {
  create: "success",
  update: "default",
  delete: "destructive",
};

export function AdminAuditLogs() {
  const [logs, setLogs] = React.useState<AuditLog[]>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [actionFilter, setActionFilter] = React.useState("");
  const [entityFilter, setEntityFilter] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const pageSize = 30;

  React.useEffect(() => {
    let active = true;
    fetchAdminAuditLogs({
      page,
      page_size: pageSize,
      ...(actionFilter ? { action: actionFilter } : {}),
      ...(entityFilter ? { entity_type: entityFilter } : {}),
    })
      .then((data) => {
        if (!active) return;
        setLogs(data.items);
        setTotal(data.total);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : "Unable to load audit logs.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, actionFilter, entityFilter]);

  if (loading && logs.length === 0 && !error) {
    return <LoadingState message="Loading audit logs…" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Audit Logs</h1>
        <p className="text-sm text-slate-500">{total} entries · every admin action is recorded</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-5 w-5 text-ai-600" /> Audit Trail
          </CardTitle>
          <CardDescription>Filter by action type or entity.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input placeholder="Filter by action (create, update, delete)…" value={actionFilter} onChange={(e) => { setActionFilter(e.target.value); setPage(1); }} />
            <Input placeholder="Filter by entity type…" value={entityFilter} onChange={(e) => { setEntityFilter(e.target.value); setPage(1); }} />
          </div>

          {error && <ErrorState title="Failed to load audit logs" description={error} />}
          {!error && logs.length === 0 && !loading ? (
            <EmptyState title="No audit logs" description="No matching audit entries found." />
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Entity</TableHead>
                    <TableHead>Entity ID</TableHead>
                    <TableHead>IP</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell className="whitespace-nowrap text-xs text-slate-500">{formatDateTime(log.created_at)}</TableCell>
                      <TableCell className="text-sm text-slate-900">{log.actor_email || "system"}</TableCell>
                      <TableCell>
                        <Badge variant={actionColors[log.action] || "secondary"}>{log.action}</Badge>
                      </TableCell>
                      <TableCell className="text-sm text-slate-600">{log.entity_type}</TableCell>
                      <TableCell className="max-w-[200px] truncate font-mono text-xs text-slate-500" title={log.entity_id || ""}>
                        {log.entity_id ? `${log.entity_id.slice(0, 8)}…` : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-slate-500">{log.ip_address || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Pagination currentPage={page} totalPages={Math.max(1, Math.ceil(total / pageSize))} onPageChange={setPage} />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}