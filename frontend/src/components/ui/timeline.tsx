"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

interface TimelineStep {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  status?: "completed" | "current" | "upcoming";
}

interface TimelineProps {
  steps: TimelineStep[];
}

export function Timeline({ steps }: TimelineProps) {
  return (
    <ol className="space-y-0">
      {steps.map((step, index) => {
        const status = step.status ?? "upcoming";
        return (
          <li key={index} className="flex gap-3.5">
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                  status === "completed" && "border-primary-600 bg-primary-600 text-white",
                  status === "current" && "border-primary-600 bg-surface text-primary-700 ring-4 ring-primary-100",
                  status === "upcoming" && "border-border-strong bg-surface text-slate-400"
                )}
                aria-hidden="true"
              >
                {step.icon || index + 1}
              </div>
              {index < steps.length - 1 && (
                <div
                  className={cn(
                    "w-px flex-1",
                    status === "completed" ? "bg-primary-400" : "bg-border-strong"
                  )}
                />
              )}
            </div>
            <div className="pb-6 pt-1">
              <p
                className={cn(
                  "text-sm font-medium",
                  status === "completed" && "text-slate-900",
                  status === "current" && "text-primary-700",
                  status === "upcoming" && "text-slate-400"
                )}
              >
                {step.title}
              </p>
              {step.description && (
                <p className="mt-1 text-sm leading-5 text-slate-500">
                  {step.description}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}