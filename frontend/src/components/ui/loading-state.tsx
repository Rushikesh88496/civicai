"use client";

import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface LoadingStateProps {
  message?: string;
  className?: string;
}

export function LoadingState({ message = "Loading...", className }: LoadingStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16", className)}>
      <Loader2 className="mb-3 h-7 w-7 animate-spin text-primary-500" />
      <p className="text-sm text-slate-500">{message}</p>
    </div>
  );
}