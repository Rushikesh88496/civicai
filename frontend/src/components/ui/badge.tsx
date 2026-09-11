"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4 transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary-600 text-white",
        primary: "border-transparent bg-primary-50 text-primary-700",
        secondary: "border-transparent bg-slate-100 text-slate-700",
        destructive: "border-transparent bg-danger-50 text-danger-700",
        success: "border-transparent bg-success-50 text-success-700",
        warning: "border-transparent bg-warning-50 text-warning-800",
        info: "border-transparent bg-info-50 text-info-700",
        ai: "border-transparent bg-ai-50 text-ai-700",
        outline: "border-border-strong bg-white text-slate-600",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };