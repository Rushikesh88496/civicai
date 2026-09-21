"use client";

import { motion } from "framer-motion";
import { Bot, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { openCivicAssistant } from "@/lib/assistant-events";

const SUGGESTIONS = [
  "What does P1 mean?",
  "Where is my complaint?",
  "Who handles my complaint?",
  "What are the most common issues in my ward?",
];

export function AssistantCard() {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      aria-label="CivicAI assistant"
      className="relative overflow-hidden rounded-3xl border border-ai-200 bg-gradient-to-br from-ai-50 via-white to-white shadow-card"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-ai-200/40 blur-3xl"
      />

      <div className="relative flex flex-col gap-6 p-6 sm:p-8 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-xl">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ai-600 text-white shadow-sm">
              <Bot className="h-5 w-5" />
            </span>
            <span className="text-xs font-medium uppercase tracking-widest text-ai-700">
              CivicAI assistant
            </span>
          </div>
          <h2 className="mt-3 text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">
            Ask anything about your complaints and your ward
          </h2>
          <p className="mt-1.5 text-sm leading-6 text-slate-600">
            Answers are grounded in official policy documents and your own
            complaint records — in English, हिंदी or मराठी.
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => openCivicAssistant(s)}
                className="rounded-full border border-border-strong bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-ai-300 hover:text-ai-700"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <Button
          size="lg"
          className="gap-2 rounded-xl bg-ai-600 hover:bg-ai-700 lg:shrink-0"
          onClick={() => openCivicAssistant()}
        >
          <Sparkles className="h-5 w-5" />
          Open assistant
        </Button>
      </div>
    </motion.section>
  );
}