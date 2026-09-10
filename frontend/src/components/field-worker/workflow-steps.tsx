"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkflowStep } from "@/lib/worker-workflow";

export function WorkflowSteps({
  steps,
  stepNumber = false,
}: {
  steps: WorkflowStep[];
  stepNumber?: boolean;
}) {
  return (
    <ol className="mt-4">
      {steps.map((s, idx) => {
        const isLast = idx === steps.length - 1;
        return (
          <li key={s.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 text-[11px] font-bold shadow-sm transition-colors",
                  s.done
                    ? "border-success-500 bg-success-500 text-white"
                    : s.current
                      ? "border-primary-600 bg-primary-600 text-white ring-4 ring-primary-100"
                      : "border-border-strong bg-surface text-slate-400"
                )}
                aria-hidden
              >
                {s.done ? (
                  <Check className="h-4 w-4" strokeWidth={3} />
                ) : stepNumber ? (
                  idx + 1
                ) : null}
              </span>
              {!isLast && (
                <span
                  className={cn(
                    "my-1 w-0.5 flex-1 rounded-full",
                    s.done ? "bg-success-300" : "bg-border-soft"
                  )}
                  aria-hidden
                />
              )}
            </div>
            <div className={cn("min-w-0 pt-0.5", !isLast && "pb-3")}>
              <p
                className={cn(
                  "text-sm leading-5",
                  s.done
                    ? "font-medium text-slate-700"
                    : s.current
                      ? "font-semibold text-slate-900"
                      : "text-slate-500"
                )}
              >
                {s.label}
              </p>
              <p
                className={cn(
                  "text-xs",
                  s.current ? "font-medium text-slate-500" : "text-slate-400"
                )}
              >
                {s.hint}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}