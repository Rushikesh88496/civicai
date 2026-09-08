"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export interface AnalyticsCardData {
  label: string;
  value: number;
  icon: React.ReactNode;
  accent: string;
}

interface AnalyticsCardsProps {
  cards: AnalyticsCardData[];
  loading: boolean;
}

export function AnalyticsCards({ cards, loading }: AnalyticsCardsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
      {cards.map((card, index) => (
        <motion.div
          key={card.label}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.05 }}
        >
          <Card className="h-full">
            <CardContent className="p-5">
              {loading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-8 w-16" />
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-slate-500">{card.label}</span>
                    <span className={cn("rounded-lg p-2", card.accent)}>{card.icon}</span>
                  </div>
                  <div className="mt-4 text-3xl font-semibold tabular-nums tracking-tight text-slate-900">
                    {card.value}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </motion.div>
      ))}
    </div>
  );
}