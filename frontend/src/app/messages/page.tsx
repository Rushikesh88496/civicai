"use client";

import * as React from "react";
import { MessageSquare } from "lucide-react";
import { MessagesLayout } from "@/components/conversations/messages-layout";
import { ConversationInbox } from "@/components/conversations/conversation-inbox";
import { ConversationThread } from "@/components/conversations/conversation-thread";
import { EmptyState } from "@/components/ui/empty-state";

export default function MessagesPage() {
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [refreshSignal, setRefreshSignal] = React.useState(0);

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const complaintId = params.get("complaint");
    if (complaintId) {
      queueMicrotask(() => setSelectedId(complaintId));
    }
  }, []);

  const refreshInbox = React.useCallback(() => {
    setRefreshSignal((signal) => signal + 1);
  }, []);

  return (
    <MessagesLayout>
      <div className="h-[calc(100vh-12rem)] min-h-[480px]">
        <div className="grid h-full gap-4 lg:grid-cols-[360px_1fr]">
          <ConversationInbox
            selectedId={selectedId}
            onSelect={setSelectedId}
            refreshSignal={refreshSignal}
          />

          <div className="min-h-0">
            {selectedId ? (
              <ConversationThread
                complaintId={selectedId}
                onBack={() => setSelectedId(null)}
                onInboxChanged={refreshInbox}
              />
            ) : (
              <div className="flex h-full items-center justify-center rounded-xl border border-border-soft bg-surface">
                <EmptyState
                  icon={<MessageSquare className="h-10 w-10 text-slate-300" />}
                  title="Select a conversation"
                  description="Choose a complaint from your inbox to view the secure conversation thread with your civic officials."
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </MessagesLayout>
  );
}