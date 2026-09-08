"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, AlertCircle, MailCheck } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthScreen } from "@/components/auth/auth-screen";
import { forgotPassword, ApiError, type ForgotPasswordResult } from "@/lib/auth-api";
import { cn } from "@/lib/utils";

export default function ForgotPasswordPage() {
  const [email, setEmail] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [result, setResult] = React.useState<ForgotPasswordResult | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError("Please enter your email address.");
      return;
    }

    setSubmitting(true);
    try {
      const data = await forgotPassword(email.trim());
      setResult(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthScreen
      title="Reset your password"
      subtitle="Enter your email and we'll send instructions to reset your password."
    >
      {result ? (
        <div className="space-y-4">
          <div className="flex flex-col items-center gap-3 rounded-xl border border-success-200 bg-success-50 px-4 py-6 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-success-100 text-success-700">
              <MailCheck className="h-6 w-6" />
            </span>
            <div>
              <p className="font-medium text-success-800">{result.message}</p>
              <p className="mt-1 text-sm text-success-700">
                Check your inbox for a reset link.
              </p>
            </div>
          </div>
          <Link href="/login" className={cn(buttonVariants(), "w-full")}>
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4 noValidate">
          <div>
            <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
              Email
            </label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
            />
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2.5 text-sm text-danger-700"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Sending…
              </>
            ) : (
              "Send Reset Link"
            )}
          </Button>
        </form>
      )}

      <p className="mt-5 text-center text-sm text-slate-500">
        Remembered your password?{" "}
        <Link href="/login" className="font-medium text-primary-600 hover:text-primary-700">
          Sign in
        </Link>
      </p>
    </AuthScreen>
  );
}