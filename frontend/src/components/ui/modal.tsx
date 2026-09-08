"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  title?: string;
  size?: "md" | "lg" | "xl";
}

const sizeMap = {
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

export function Modal({ open, onClose, children, title, size = "md" }: ModalProps) {
  React.useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    const original = document.activeElement as HTMLElement | null;
    return () => {
      document.body.style.overflow = "unset";
      original?.focus?.();
    };
  }, [open]);

  React.useEffect(() => {
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (open) document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label={title}
        >
          <motion.div
            className="fixed inset-0 bg-navy-950/50 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              "relative z-10 flex max-h-[90vh] w-full flex-col overflow-hidden rounded-xl border border-border-soft bg-surface shadow-dialog",
              sizeMap[size]
            )}
          >
            {title && (
              <div className="flex items-center justify-between border-b border-border-soft px-5 py-3.5">
                <h2 className="text-base font-semibold tracking-tight text-slate-900">
                  {title}
                </h2>
                <button
                  onClick={onClose}
                  className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                  aria-label="Close dialog"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            )}
            <div className="flex-1 overflow-y-auto">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}