"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Bell, ClipboardList, FilePlus2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { openCivicAssistant } from "@/lib/assistant-events";

interface QuickActionCardsProps {
  complaintsTotal: number;
  unreadCount: number;
}

const cardBase =
  "group relative flex flex-col justify-between overflow-hidden rounded-2xl border border-border-soft bg-surface p-5 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-200 hover:shadow-card-hover";

export function QuickActionCards({
  complaintsTotal,
  unreadCount,
}: QuickActionCardsProps) {
  const actions = [
    {
      href: "/report",
      title: "Report an issue",
      description: "Describe a problem and attach photos or video",
      icon: FilePlus2,
      accent: "bg-primary-50 text-primary-600 group-hover:bg-primary-600 group-hover:text-white",
      badge: null as string | null,
    },
    {
      href: "/dashboard/complaints",
      title: "My complaints",
      description: "Track status and updates on your reports",
      icon: ClipboardList,
      accent: "bg-ai-50 text-ai-600 group-hover:bg-ai-600 group-hover:text-white",
      badge: complaintsTotal > 0 ? String(complaintsTotal) : null,
    },
    {
      href: "/dashboard/notifications",
      title: "Notifications",
      description: "Realtime updates about your complaints",
      icon: Bell,
      accent: "bg-warning-50 text-warning-600 group-hover:bg-warning-500 group-hover:text-white",
      badge: unreadCount > 0 ? String(unreadCount) : null,
    },
  ] as const;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {actions.map((action, index) => {
        const inner = (
          <div className={cardBase}>
            <div className="flex items-start justify-between gap-3">
              <span
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded-xl transition-colors",
                  action.accent
                )}
              >
                <action.icon className="h-5 w-5" />
              </span>
              {action.badge && (
                <span className="inline-flex h-6 min-w-6 items-center justify-center rounded-full bg-slate-100 px-1.5 text-xs font-semibold text-slate-700">
                  {action.badge}
                </span>
              )}
            </div>
            <div className="mt-4">
              <div className="text-sm font-semibold text-slate-900">{action.title}</div>
              <div className="mt-0.5 text-xs leading-5 text-slate-500">{action.description}</div>
            </div>
          </div>
        );

        return (
          <motion.div
            key={action.href}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.05 * index, ease: "easeOut" }}
          >
            <Link href={action.href} className="block h-full focus:outline-none">
              {inner}
            </Link>
          </motion.div>
        );
      })}

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.15, ease: "easeOut" }}
      >
        <button
          type="button"
          onClick={() => openCivicAssistant()}
          className={cn(cardBase, "w-full text-left focus:outline-none")}
        >
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-ai-500 text-white">
            <Sparkles className="h-5 w-5" />
          </span>
          <span className="mt-4 block">
            <span className="block text-sm font-semibold text-slate-900">CivicAI assistant</span>
            <span className="mt-0.5 block text-xs leading-5 text-slate-500">
              Ask about priority, your ward or any policy
            </span>
          </span>
        </button>
      </motion.div>
    </div>
  );
}