"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Loader2, MessageCircle, Send, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/components/auth/auth-provider";
import {
  type AssistantMessageItem,
  type AssistantSource,
  clearAssistantConversation,
  fetchAssistantConversation,
  streamAssistantAnswer,
} from "@/lib/assistant-api";

const SUGGESTIONS = [
  "What does P1 mean?",
  "Where is my complaint?",
  "Who handles my complaint?",
  "What are the most common issues in my ward?",
];

function timeLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function SourceChips({ sources }: { sources: AssistantSource[] }) {
  if (!sources.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 pt-1.5">
      {sources.map((source, i) => (
        <Badge
          key={`${source.reference}-${i}`}
          variant="outline"
          className="max-w-full px-2 py-0.5 text-[10px] font-medium leading-tight text-gray-500"
          title={source.reference}
        >
          {source.reference}
        </Badge>
      ))}
    </div>
  );
}

function AssistantMessageBubble({ message }: { message: AssistantMessageItem }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed",
          isUser
            ? "rounded-br-sm bg-blue-600 text-white"
            : "rounded-bl-sm border border-gray-200 bg-white text-gray-800"
        )}
      >
        <div className="whitespace-pre-wrap">{message.content}</div>
        {!isUser && <SourceChips sources={message.sources} />}
        <div
          className={cn(
            "mt-1 text-[10px]",
            isUser ? "text-blue-200" : "text-gray-400"
          )}
        >
          {timeLabel(message.created_at ?? null)}
          {!isUser && message.generated_by === "synthesized" ? " · synthesized" : ""}
        </div>
      </div>
    </div>
  );
}

export function AssistantWidget() {
  const { user } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [input, setInput] = React.useState("");
  const [messages, setMessages] = React.useState<AssistantMessageItem[]>([]);
  const [streaming, setStreaming] = React.useState(false);
  const [loaded, setLoaded] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const loadHistory = React.useCallback(async () => {
    if (loaded) return;
    try {
      const conversation = await fetchAssistantConversation();
      setMessages(conversation.messages);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load conversation.");
    } finally {
      setLoaded(true);
    }
  }, [loaded]);

  // Allow other citizen surfaces (e.g. the home-page assistant card) to open
  // the floating widget, optionally prefilling a question.
  React.useEffect(() => {
    function onOpen(event: Event) {
      const detail = (event as CustomEvent<{ query?: string }>).detail;
      setOpen(true);
      void loadHistory();
      if (detail?.query?.trim()) setInput(detail.query);
    }
    window.addEventListener("civicai:open-assistant", onOpen);
    return () => window.removeEventListener("civicai:open-assistant", onOpen);
  }, [loadHistory]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) void loadHistory();
  };

  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const send = async () => {
    const question = input.trim();
    if (!question || busy || streaming) return;
    setInput("");
    setError(null);
    const userMessage: AssistantMessageItem = {
      id: `local-user-${Date.now()}`,
      role: "user",
      content: question,
      sources: [],
      generated_by: null,
      created_at: new Date().toISOString(),
    };
    const assistantId = `local-assistant-${Date.now()}`;
    const placeholder: AssistantMessageItem = {
      id: assistantId,
      role: "assistant",
      content: "",
      sources: [],
      generated_by: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage, placeholder]);
    setStreaming(true);
    setBusy(true);
    try {
      const chunks: string[] = [];
      await streamAssistantAnswer(question, {
        onEvent: (event, data) => {
          if (event === "delta" && typeof data.text === "string") {
            chunks.push(data.text);
            const text = chunks.join("");
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: text } : m))
            );
          }
          if (event === "sources" && Array.isArray(data.sources)) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, sources: data.sources as AssistantSource[] }
                  : m
              )
            );
          }
          if (event === "done") {
            const answer = typeof data.answer === "string" ? data.answer : chunks.join("");
            const language = typeof data.language === "string" ? data.language : undefined;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: answer,
                      generated_by: "groq",
                      id: `streamed-${assistantId}`,
                      ...(language ? { language } : {}),
                    }
                  : m
              )
            );
          }
        },
      }, user?.profile.language);
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content:
                  m.content ||
                  (e instanceof Error ? e.message : "The assistant could not answer right now."),
              }
            : m
        )
      );
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setStreaming(false);
      setBusy(false);
    }
  };

  const handleClear = async () => {
    setBusy(true);
    setError(null);
    try {
      await clearAssistantConversation();
      setMessages([]);
      setLoaded(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not clear the conversation.");
    } finally {
      setBusy(false);
    }
  };

  const isCitizen = user?.role.name === "CITIZEN";
  if (!isCitizen) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => handleOpenChange(!open)}
        aria-label={open ? "Close AI assistant" : "Open AI assistant"}
        className="fixed bottom-5 right-5 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-lg shadow-blue-600/30 transition-transform hover:scale-105"
      >
        {open ? <X className="h-6 w-6" /> : <Bot className="h-7 w-7" />}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.97 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="fixed bottom-24 right-5 z-50 flex h-[560px] w-[380px] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-white">
                  <MessageCircle className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-gray-900">CivicAgent Assistant</p>
                  <p className="text-xs text-gray-500">Your municipal helper</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => void handleClear()}
                disabled={busy}
                className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:opacity-40"
                aria-label="Clear conversation"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            {/* Messages */}
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto bg-gray-50 px-4 py-3">
              {messages.length === 0 && !streaming ? (
                <div className="py-6 text-center">
                  <Bot className="mx-auto h-8 w-8 text-gray-300" />
                  <p className="mt-2 text-sm font-medium text-gray-700">
                    Ask about your complaints, priority, wards or municipal policy.
                  </p>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <Button
                        key={s}
                        type="button"
                        variant="outline"
                        size="sm"
                        className="rounded-full text-xs text-gray-600"
                        onClick={() => {
                          setInput(s);
                        }}
                      >
                        {s}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m) => <AssistantMessageBubble key={m.id} message={m} />)
              )}
              {streaming && (
                <div className="flex items-center gap-2 pl-1 text-xs text-gray-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  CivicAgent is answering…
                </div>
              )}
            </div>

            {error && (
              <div className="border-t border-red-100 bg-red-50 px-4 py-2 text-xs text-red-700">
                {error}
              </div>
            )}

            {/* Composer */}
            <div className="border-t border-gray-100 p-3">
              <div className="flex items-end gap-2">
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder="Ask your municipality anything…"
                  className="min-h-[44px] max-h-32 resize-none py-2.5 text-sm"
                  rows={1}
                  disabled={busy}
                />
                <Button
                  type="button"
                  size="icon"
                  className="h-[44px] w-[44px] shrink-0"
                  onClick={() => void send()}
                  disabled={busy || !input.trim()}
                  aria-label="Send question"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
              <p className="mt-1.5 text-[10px] leading-tight text-gray-400">
                Answers are grounded in official policy documents and your own complaint records.
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}