"use client";

import * as React from "react";
import { Navbar } from "@/components/layout/navbar";
import { Footer } from "@/components/layout/footer";
import { ReportWizard } from "@/components/report/report-wizard";

export default function ReportPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-1 py-8">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900">Report an Issue</h1>
            <p className="text-gray-500 mt-1">
              Submit a civic complaint with photos, a short video, and your location. Our team will
              review, prioritize, and route it automatically.
            </p>
          </div>

          <ReportWizard />
        </div>
      </main>
      <Footer />
    </div>
  );
}
