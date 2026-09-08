"use client";

import { TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  title?: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description = "An unexpected error occurred. Please try again.",
  action,
  className,
}: ErrorStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-4 py-12 text-center", className)}>
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-lg border border-danger-100 bg-danger-50 text-danger-500">
        <TriangleAlert className="h-7 w-7" />
      </div>
      <h3 className="mb-1 text-base font-semibold text-slate-900">{title}</h3>
      <p className="mb-4 max-w-sm text-sm leading-5 text-slate-500">{description}</p>
      {action}
    </div>
  );
}