"use client";

import * as React from "react";
import { MessageSquare, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchConversations,
  type ConversationListItem,
} from "@/lib/conversation-api";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { timeAgo } from "@/components/dashboard/format";

interface ConversationInboxProps {
  selectedId: string | null;
  onSelect: (complaintId: string) => void;
  refreshSignal: number;
}

function progressLabel(value: string | null): string {
  const labels: Record<string, string> = {
    SUBMITTED: "Submitted",
    AI_ANALYZING: "Analyzing",
    EVIDENCE_VERIFIED: "Evidence verified",
    WARD_IDENTIFIED: "Ward identified",
    PRIORITIZED: "Prioritized",
    DEPARTMENT_ASSIGNED: "Department assigned",
    WORK_ORDER_CREATED: "Work order created",
    WORKER_ASSIGNED: "Worker assigned",
    IN_PROGRESS: "In progress",
    RESOLVED: "Resolved",
    CLOSED: "Closed",
    ESCALATED: "Escalated",
    CITIZEN_VERIFIED: "Citizen verified",
    OPEN: "Open",
  };
  return value ? (labels[value] ?? value) : "";
}

function avatarColor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash << 5) - hash + seed.charCodeAt(i);
    hash |= 0;
  }
  const colors = [
    "bg-primary-500",
    "bg-success-500",
    "bg-warning-500",
    "bg-rose-500",
    "bg-ai-500",
    "bg-info-500",
  ];
  return colors[Math.abs(hash) % colors.length];
}

export function ConversationInbox({
  selectedId,
  onSelect,
  refreshSignal,
}: ConversationInboxProps) {
  const [items, setItems] = React.useState<ConversationListItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);

  const reload = React.useCallback(() => {
    setLoading(true);
    setError(null);
    setTick((t) => t + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    fetchConversations()
      .then((data) => {
        if (active) {
          setItems(data.items);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(
          err instanceof Error ? err.message : "Could not load conversations."
        );
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick, refreshSignal]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-border-soft bg-surface shadow-sm">
      <div className="flex items-center justify-between border-b border-border-soft px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary-600" />
          <h2 className="text-sm font-semibold text-slate-900">Conversations</h2>
        </div>
        <button
          onClick={reload}
          className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          aria-label="Refresh conversations"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {error ? (
          <ErrorState
            title="Could not load conversations"
            description={error}
            className="py-8"
            action={
              <button
                onClick={reload}
                className="text-sm font-medium text-primary-600 hover:underline"
              >
                Try again
              </button>
            }
          />
        ) : loading ? (
          <div className="space-y-2 p-3">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<MessageSquare className="h-8 w-8 text-slate-400" />}
            title="No conversations yet"
            description="Start a conversation from one of your complaints, or as a civic official reply to a citizen's complaint."
            className="py-10"
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {items.map((item) => {
              const active = item.complaint_id === selectedId;
              const initials = (item.last_author_name || "?")
                .split(" ")
                .filter(Boolean)
                .slice(0, 2)
                .map((part) => part[0]?.toUpperCase() ?? "")
                .join("");
              return (
                <li key={item.complaint_id}>
                  <button
                    onClick={() => onSelect(item.complaint_id)}
                    className={cn(
                      "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors",
                      active ? "bg-primary-50" : "hover:bg-slate-50"
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white",
                        avatarColor(item.complaint_id)
                      )}
                    >
                      {initials}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-2">
                        <span className="truncate text-sm font-medium text-slate-900">
                          {item.complaint_title}
                        </span>
                        {item.unread_count > 0 && (
                          <Badge variant="destructive" className="shrink-0">
                            {item.unread_count}
                          </Badge>
                        )}
                      </span>
                      {item.last_message && (
                        <span className="mt-0.5 block truncate text-sm text-slate-500">
                          {item.last_author_name ? (
                            <span className="font-medium text-slate-700">
                              {item.last_author_name}:{" "}
                            </span>
                          ) : null}
                          {item.last_message}
                        </span>
                      )}
                      <span className="mt-1 flex items-center gap-2">
                        <span className="text-xs text-slate-400">
                          {progressLabel(item.complaint_status)}
                        </span>
                        {item.last_message_at && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span className="text-xs text-slate-400">
                              {timeAgo(item.last_message_at)}
                            </span>
                          </>
                        )}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}