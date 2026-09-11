"use client";

import * as React from "react";
import {
  ArrowLeft,
  Bot,
  Check,
  Loader2,
  Paperclip,
  RefreshCw,
  Send,
  FileText,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchAiSummary,
  fetchConversation,
  markConversationRead,
  sendMessage,
  uploadAttachment,
  type AiDraft,
  type ConversationThread,
} from "@/lib/conversation-api";
import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { AiDraftModal } from "@/components/conversations/ai-draft-modal";
import { formatDateTime } from "@/components/dashboard/format";

const ROLE_LABELS: Record<string, string> = {
  CITIZEN: "Citizen",
  WARD_REPRESENTATIVE: "Ward Representative",
  OFFICER: "Official",
  ADMIN: "Administrator",
  FIELD_WORKER: "Field Worker",
};

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ConversationThreadProps {
  complaintId: string;
  onBack: () => void;
  onInboxChanged: () => void;
}

export function ConversationThread({
  complaintId,
  onBack,
  onInboxChanged,
}: ConversationThreadProps) {
  const { user } = useAuth();
  const [thread, setThread] = React.useState<ConversationThread | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [body, setBody] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [staged, setStaged] = React.useState<
    Array<{ id: string; original_filename: string; content_type: string; size_bytes: number; url: string | null }>
  >([]);
  const [draft, setDraft] = React.useState<AiDraft | null>(null);
  const [draftLoading, setDraftLoading] = React.useState(false);
  const [draftModalOpen, setDraftModalOpen] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const messagesEndRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError(null);
      setThread(null);
      setBody("");
      setStaged([]);
      try {
        const data = await fetchConversation(complaintId);
        if (!active) return;
        setThread(data);
        const me = user?.id;
        const hasUnread =
          me != null &&
          data.messages.some(
            (m) => m.author_id !== me && !m.is_read_by_me
          );
        if (hasUnread) {
          const updated = await markConversationRead(complaintId);
          if (active) {
            setThread(updated);
            onInboxChanged();
          }
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not load this conversation."
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
    // reload whenever the selected complaint changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [complaintId]);

  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread?.messages.length]);

  const handleSend = async () => {
    const text = body.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const updated = await sendMessage(
        complaintId,
        text,
        staged.map((s) => s.id)
      );
      setThread(updated);
      setBody("");
      setStaged([]);
      onInboxChanged();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not send your message."
      );
    } finally {
      setSending(false);
    }
  };

  const handleFile = async (file: File | undefined | null) => {
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const attachment = await uploadAttachment(complaintId, file);
      setStaged((prev) => [...prev, attachment]);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not upload the attachment."
      );
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDraft = async () => {
    setDraftLoading(true);
    setDraft(null);
    setDraftModalOpen(true);
    try {
      const result = await fetchAiSummary(complaintId);
      setDraft(result);
    } catch (err) {
      // surface the failure inside the modal as a short message
      setError(
        err instanceof Error ? err.message : "Could not generate an AI draft."
      );
      setDraftModalOpen(false);
    } finally {
      setDraftLoading(false);
    }
  };

  if (!thread) {
    if (loading) {
      return (
        <div className="flex h-full items-center justify-center rounded-xl border border-border-soft bg-surface py-24">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading conversation…
          </div>
        </div>
      );
    }
    return (
      <div className="rounded-xl border border-border-soft bg-surface">
        <ErrorState
          title="Could not open this conversation"
          description={error || "Something went wrong."}
          action={
            <Button variant="outline" size="sm" onClick={onBack}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to conversations
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-border-soft bg-surface shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-soft px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <button
            onClick={onBack}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 lg:hidden"
            aria-label="Back to conversations"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-slate-900">
              {thread.complaint_title}
            </h2>
            <span className="text-xs text-slate-400">
              {thread.complaint_status ?? "Conversation"}
              {thread.messages.length > 0 &&
                ` · ${thread.messages.length} message${thread.messages.length === 1 ? "" : "s"}`}
            </span>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={handleDraft} disabled={draftLoading}>
          {draftLoading ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Bot className="mr-2 h-4 w-4" />
          )}
          AI summary
        </Button>
      </div>

      {error && thread && (
        <div className="border-b border-danger-100 bg-danger-50 px-4 py-2 text-sm text-danger-700">
          {error}
        </div>
      )}

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {thread.messages.length === 0 ? (
          <EmptyState
            icon={<RefreshCw className="h-8 w-8 text-slate-400" />}
            title="No messages yet"
            description="Start the conversation — the authorized civic officials will be able to reply."
            className="py-16"
          />
        ) : (
          thread.messages.map((message) => {
            const mine = message.author_id === user?.id;
            return (
              <div
                key={message.id}
                className={cn("flex gap-2", mine ? "justify-end" : "justify-start")}
              >
                <div
                  className={cn(
                    "max-w-[80%] rounded-2xl px-4 py-2.5",
                    mine
                      ? "rounded-br-md bg-primary-600 text-white"
                      : "rounded-bl-md border border-border-soft bg-surface text-slate-800"
                  )}
                >
                  {!mine && (
                    <div className="mb-1 flex items-center gap-2">
                      <span className="text-xs font-semibold text-slate-900">
                        {message.author_name || "Civic official"}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                        {roleLabel(message.role)}
                      </span>
                    </div>
                  )}
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {message.body}
                  </p>

                  {message.attachments.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {message.attachments.map((attachment) => (
                        <a
                          key={attachment.id}
                          href={attachment.url || "#"}
                          target={attachment.url ? "_blank" : undefined}
                          rel="noreferrer"
                          className={cn(
                            "flex items-center gap-2 rounded-lg p-2 text-xs font-medium",
                            mine
                              ? "bg-primary-700/60 text-white hover:bg-primary-700"
                              : "bg-slate-100 text-slate-700 hover:bg-slate-200",
                            !attachment.url && "pointer-events-none opacity-80"
                          )}
                        >
                          <FileText className="h-3.5 w-3.5 shrink-0" />
                          <span className="min-w-0 flex-1 truncate">
                            {attachment.original_filename}
                          </span>
                          <span className={mine ? "text-primary-100" : "text-slate-400"}>
                            {formatSize(attachment.size_bytes)}
                          </span>
                        </a>
                      ))}
                    </div>
                  )}

                  <div
                    className={cn(
                      "mt-1 flex items-center gap-2 text-[10px]",
                      mine ? "text-primary-200" : "text-slate-400"
                    )}
                  >
                    <span>{formatDateTime(message.created_at)}</span>
                    {mine && message.read_by.length > 0 && (
                      <span className="inline-flex items-center gap-1 text-success-300">
                        <Check className="h-3 w-3" />
                        {message.read_by_all
                          ? "Read by all"
                          : `Read by ${message.read_by.map((r) => r.user_name || "participant").join(", ")}`}
                      </span>
                    )}
                    {!mine && message.is_read_by_me && (
                      <span className="inline-flex items-center gap-1 text-success-500">
                        <Check className="h-3 w-3" />
                        Read
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-border-soft p-3">
        {staged.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {staged.map((attachment) => (
              <span
                key={attachment.id}
                className="inline-flex items-center gap-2 rounded-lg border border-primary-200 bg-primary-50 px-2 py-1 text-xs font-medium text-primary-700"
              >
                <FileText className="h-3.5 w-3.5" />
                {attachment.original_filename}
                <button
                  onClick={() =>
                    setStaged((prev) => prev.filter((s) => s.id !== attachment.id))
                  }
                  className="text-primary-500 hover:text-primary-700"
                  aria-label={`Remove ${attachment.original_filename}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Write a message… (Enter to send, Shift+Enter for a new line)"
            className="min-h-[44px] max-h-40"
            maxLength={4000}
          />
          <div className="flex shrink-0 gap-1.5">
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
            <Button
              variant="outline"
              size="icon"
              type="button"
              disabled={uploading}
              onClick={() => fileInputRef.current?.click()}
              aria-label="Attach a file"
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Paperclip className="h-4 w-4" />
              )}
            </Button>
            <Button
              size="icon"
              type="button"
              disabled={!body.trim() || sending}
              onClick={handleSend}
              aria-label="Send message"
            >
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </div>

      <AiDraftModal
        open={draftModalOpen}
        draft={draft}
        loading={draftLoading}
        onUseReply={() => {
          if (draft) setBody(draft.suggested_reply);
          setDraftModalOpen(false);
        }}
        onClose={() => setDraftModalOpen(false)}
      />
    </div>
  );
}