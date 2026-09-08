"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number;
  max?: number;
  tone?: "primary" | "success" | "warning" | "danger";
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, max = 100, tone = "primary", ...props }, ref) => {
    const percentage = Math.min(Math.max((value / max) * 100, 0), 100);
    const toneClass = {
      primary: "bg-primary-600",
      success: "bg-success-500",
      warning: "bg-warning-500",
      danger: "bg-danger-500",
    }[tone];

    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        className={cn("relative h-2 w-full overflow-hidden rounded-full bg-slate-200/70", className)}
        {...props}
      >
        <div
          className={cn("h-full rounded-full transition-all duration-500", toneClass)}
          style={{ width: `${percentage}%` }}
        />
      </div>
    );
  }
);
Progress.displayName = "Progress";

export { Progress };