"use client";

// Client helpers for the Part 25 Citizen AI Assistant (RAG) widget.
// Mirror of the backend /api/v1/assistant schema (answer + SSE streaming +
// conversation persistence). Reuses the auth-api access-token machinery so the
// assistant is only ever called for the authenticated user.

import { ApiError, authorizedFetch, getAccessToken, readErrorMessage } from "@/lib/auth-api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --------------------------------------------------------------------------- //
// Types (mirror the backend /assistant schemas)
// --------------------------------------------------------------------------- //

export interface AssistantSource {
  reference: string;
  title: string;
  relevance: number;
}

export interface AssistantAnswer {
  answer: string;
  sources: AssistantSource[];
  generated_by: string;
  used_rag: boolean;
  ai_prediction: boolean;
  disclaimer: string;
  // Part 26: language detected from the question and the resolved reply language.
  detected_language?: string;
  language?: string;
}

export interface AssistantMessageItem {
  id: string;
  role: string;
  content: string;
  sources: AssistantSource[];
  generated_by: string | null;
  created_at: string;
  language?: string | null;
}

export interface AssistantConversation {
  messages: AssistantMessageItem[];
  disclaimer: string;
  language?: string | null;
}

export interface AssistantClearResult {
  cleared: boolean;
  messages_deleted: number;
}

// --------------------------------------------------------------------------- //
// Authenticated transport
// --------------------------------------------------------------------------- //

async function authorized<T>(path: string, init: RequestInit = {}): Promise<T> {
  return authorizedFetch<T>(path, init);
}

// --------------------------------------------------------------------------- //
// API
// --------------------------------------------------------------------------- //

export async function askAssistant(
  question: string,
  language?: string | null
): Promise<AssistantAnswer> {
  return authorized<AssistantAnswer>("/api/v1/assistant/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, ...(language ? { language } : {}) }),
  });
}

export async function fetchAssistantConversation(): Promise<AssistantConversation> {
  return authorized<AssistantConversation>("/api/v1/assistant/conversation");
}

export async function clearAssistantConversation(): Promise<AssistantClearResult> {
  return authorized<AssistantClearResult>("/api/v1/assistant/conversation", {
    method: "DELETE",
  });
}

// --------------------------------------------------------------------------- //
// Streaming (Server-Sent Events)
// --------------------------------------------------------------------------- //

export interface AssistantStreamCallbacks {
  onEvent: (event: string, data: Record<string, unknown>) => void;
}

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

async function* sseEvents(res: Response): AsyncGenerator<SseEvent> {
  if (!res.body) {
    throw new ApiError(500, "The stream returned an empty body.");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      const block = buffer.slice(0, separator).replace(/\r\n/g, "\n");
      buffer = buffer.slice(separator + 2);
      const lines = block.split("\n").filter(Boolean);
      const event =
        lines.find((line) => line.startsWith("event: "))?.slice(7) ?? "message";
      const dataLine = lines.find((line) => line.startsWith("data: "));
      if (dataLine) {
        try {
          yield { event, data: JSON.parse(dataLine.slice(6)) as Record<string, unknown> };
        } catch {
          // Skip malformed events instead of killing the stream.
        }
      }
      separator = buffer.indexOf("\n\n");
    }
  }
}

export async function streamAssistantAnswer(
  question: string,
  callbacks: AssistantStreamCallbacks,
  language?: string | null
): Promise<AssistantAnswer> {
  const token = await getAccessToken();
  if (!token) {
    throw new ApiError(401, "Not authenticated.");
  }
  const res = await fetch(`${API_BASE_URL}/api/v1/assistant/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question, ...(language ? { language } : {}) }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorMessage(res));
  }
  if (!res.headers.get("content-type")?.includes("text/event-stream")) {
    throw new ApiError(500, "Unexpected streaming response type.");
  }

  const accumulated: string[] = [];
  let sources: AssistantSource[] = [];
  let finalAnswer = "";
  let usedRag = false;
  let generatedBy = "synthesized";
  let detectedLanguage = "en";
  let language_ = "en";

  for await (const { event, data } of sseEvents(res)) {
    callbacks.onEvent(event, data);
    if (event === "meta" && typeof data.generated_by === "string") {
      generatedBy = data.generated_by;
    }
    if (event === "meta" && typeof data.detected_language === "string") {
      detectedLanguage = data.detected_language;
    }
    if (event === "meta" && typeof data.language === "string") {
      language_ = data.language;
    }
    if (event === "delta" && typeof data.text === "string") {
      accumulated.push(data.text);
    }
    if (event === "sources" && Array.isArray(data.sources)) {
      sources = data.sources as AssistantSource[];
    }
    if (event === "done") {
      finalAnswer = typeof data.answer === "string" ? data.answer : accumulated.join("");
      usedRag = data.used_rag === true;
      if (typeof data.detected_language === "string") {
        detectedLanguage = data.detected_language;
      }
      if (typeof data.language === "string") {
        language_ = data.language;
      }
      break;
    }
  }

  return {
    answer: finalAnswer || accumulated.join("").trim(),
    sources,
    generated_by: generatedBy,
    used_rag: usedRag,
    ai_prediction: true,
    disclaimer: "",
    detected_language: detectedLanguage,
    language: language_,
  };
}