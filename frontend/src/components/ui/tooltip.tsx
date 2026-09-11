"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

interface TooltipProps {
  content: string;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}

export function Tooltip({ content, children, side = "top" }: TooltipProps) {
  const [show, setShow] = React.useState(false);

  const positionClasses: Record<string, string> = {
    top: "-translate-x-1/2 left-1/2",
    bottom: "-translate-x-1/2 left-1/2",
    left: "-translate-y-1/2 top-1/2",
    right: "-translate-y-1/2 top-1/2",
  };

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
      role="tooltip"
      aria-label={content}
    >
      {children}
      {show && (
        <span
          className={cn(
            "pointer-events-none absolute z-50 rounded-md bg-navy-900 px-2.5 py-1.5 text-xs font-medium leading-4 text-white shadow-popover",
            positionClasses[side],
            side === "top" && "bottom-full mb-1.5",
            side === "bottom" && "top-full mt-1.5",
            side === "left" && "right-full mr-1.5",
            side === "right" && "left-full ml-1.5"
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}