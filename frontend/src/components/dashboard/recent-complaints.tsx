"use client";

import * as React from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge, PriorityBadge, CategoryBadge } from "@/components/dashboard/status-badge";
import { formatDate } from "@/components/dashboard/format";
import type { Complaint } from "@/lib/citizen-api";
import { Files, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";

const PAGE_SIZE = 6;

interface RecentComplaintsProps {
  complaints: Complaint[];
  loading: boolean;
  limit?: number;
  showFilters?: boolean;
}

export function RecentComplaints({
  complaints,
  loading,
  limit,
  showFilters = true,
}: RecentComplaintsProps) {
  const [query, setQuery] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState("ALL");
  const [priorityFilter, setPriorityFilter] = React.useState("ALL");
  const [page, setPage] = React.useState(1);

  const filtered = React.useMemo(() => {
    let rows = complaints;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      rows = rows.filter(
        (c) =>
          c.title.toLowerCase().includes(q) ||
          (c.category || "").toLowerCase().includes(q) ||
          (c.location || "").toLowerCase().includes(q)
      );
    }
    if (statusFilter !== "ALL") {
      rows = rows.filter((c) => c.status === statusFilter);
    }
    if (priorityFilter !== "ALL") {
      rows = rows.filter((c) => c.priority === priorityFilter);
    }
    return rows;
  }, [complaints, query, statusFilter, priorityFilter]);

  const visible = limit ? filtered.slice(0, limit) : filtered;

  const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedRows = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  return (
    <Card>
      <CardHeader className="gap-1">
        <CardTitle>Recent Complaints</CardTitle>
        <CardDescription>
          Your submitted complaints with the latest status updates.
        </CardDescription>
        {showFilters && (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:flex sm:items-center">
            <div className="relative sm:w-64">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="pl-9"
                placeholder="Search title, location…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="ALL">All statuses</option>
              <option value="OPEN">Open</option>
              <option value="IN_PROGRESS">In Progress</option>
              <option value="RESOLVED">Resolved</option>
              <option value="ESCALATED">Escalated</option>
            </Select>
            <Select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
              <option value="ALL">All priorities</option>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
            </Select>
          </div>
        )}
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-4">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : pagedRows.length === 0 ? (
          <EmptyState
            icon={<Files className="h-8 w-8 text-slate-300" />}
            title="No complaints found"
            description="No complaints match your filters yet. Try adjusting the search or filters."
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Complaint</TableHead>
                  <TableHead className="hidden md:table-cell">Category</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden lg:table-cell">Location</TableHead>
                  <TableHead className="hidden sm:table-cell">Reported</TableHead>
                  <TableHead className="text-right"><span className="sr-only">Actions</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagedRows.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/complaints/${c.id}`}
                        className="font-medium text-slate-900 line-clamp-1 hover:text-primary-600 hover:underline"
                      >
                        {c.title}
                      </Link>
                      <div className="text-xs text-slate-400 md:hidden">{c.category}</div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <CategoryBadge value={c.category} />
                    </TableCell>
                    <TableCell>
                      <PriorityBadge value={c.priority} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge value={c.status} />
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-sm text-slate-600 line-clamp-1">
                      {c.location || "—"}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell text-sm text-slate-500">
                      {formatDate(c.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Link href={`/messages?complaint=${c.id}`}>
                        <Button variant="ghost" size="sm" className="gap-1 text-primary-600 hover:text-primary-700">
                          <MessageSquare className="h-4 w-4" />
                          Message
                        </Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {totalPages > 1 && (
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={setPage}
                className="mt-4"
              />
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}