"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, PlusCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { REPORT_CATEGORIES } from "@/lib/complaint-categories";

export function ReportCtaSection() {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      aria-label="Report a civic issue"
      className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary-700 via-primary-800 to-navy-900 shadow-card"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-white/10 blur-3xl"
      />

      <div className="relative p-6 sm:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-lg">
            <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
              Spot something broken in your area?
            </h2>
            <p className="mt-2 text-sm leading-6 text-primary-100 sm:text-base">
              Report a pothole, water leak, overflowing garbage or any other civic
              issue in under a minute. Photographs and location help us route it
              to the right team faster.
            </p>
            <Link href="/report" className="mt-5 inline-block">
              <Button
                size="lg"
                className="gap-2 rounded-xl bg-white text-primary-800 shadow-lg shadow-black/10 hover:bg-slate-100"
              >
                <PlusCircle className="h-5 w-5" />
                Start a report
              </Button>
            </Link>
          </div>

          <div className="grid w-full grid-cols-2 gap-2.5 sm:grid-cols-4 lg:w-[460px]">
            {REPORT_CATEGORIES.map((cat) => (
              <Link
                key={cat.value}
                href={`/report?category=${cat.value}`}
                title={cat.description}
                className="group flex flex-col items-start gap-2 rounded-2xl border border-white/15 bg-white/10 p-3 backdrop-blur-sm transition-colors hover:bg-white/20"
              >
                <cat.icon className="h-5 w-5 text-white" />
                <span className="text-xs font-medium leading-tight text-white">
                  {cat.label}
                </span>
                <ArrowRight className="h-3.5 w-3.5 text-white/60 transition-transform group-hover:translate-x-0.5" />
              </Link>
            ))}
          </div>
        </div>
      </div>
    </motion.section>
  );
}