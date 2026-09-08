"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, CheckCircle2, AlertTriangle, Info, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "info" | "warning" | "loading";

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  addToast: (message: string, type?: ToastType) => void;
}

const ToastContext = React.createContext<ToastContextType>({ addToast: () => {} });

export function useToast() {
  return React.useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const addToast = React.useCallback((message: string, type: ToastType = "info") => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    if (type !== "loading") {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 5000);
    }
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const iconMap = {
    success: <CheckCircle2 className="h-5 w-5 text-success-500" />,
    error: <AlertTriangle className="h-5 w-5 text-danger-500" />,
    info: <Info className="h-5 w-5 text-info-500" />,
    warning: <AlertTriangle className="h-5 w-5 text-warning-500" />,
    loading: <Loader2 className="h-5 w-5 animate-spin text-primary-500" />,
  };

  const accentMap = {
    success: "border-success-200",
    error: "border-danger-200",
    info: "border-info-200",
    warning: "border-warning-200",
    loading: "border-primary-200",
  };

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div
        role="region"
        aria-label="Notifications"
        className="fixed bottom-4 right-4 z-[100] flex max-w-sm flex-col gap-2"
      >
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              transition={{ duration: 0.18 }}
              className={cn(
                "flex items-start gap-3 rounded-lg border bg-surface p-3.5 pr-2 shadow-popover",
                accentMap[toast.type]
              )}
              role="status"
            >
              <span className="mt-0.5 shrink-0">{iconMap[toast.type]}</span>
              <p className="flex-1 text-sm leading-5 text-slate-700">{toast.message}</p>
              <button
                onClick={() => removeToast(toast.id)}
                className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}