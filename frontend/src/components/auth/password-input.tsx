"use client";

import * as React from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { evaluatePassword } from "@/lib/password-strength";

interface PasswordInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** Show a live strength meter and requirement checklist above the field. */
  showStrength?: boolean;
}

export function PasswordInput({ showStrength, className, value, ...props }: PasswordInputProps) {
  const [visible, setVisible] = React.useState(false);
  const strength = evaluatePassword(value as string);

  return (
    <div>
      <div className="relative">
        <Input
          {...props}
          value={value}
          type={visible ? "text" : "password"}
          className={cn("pr-10", className)}
        />
        <button
          type="button"
          aria-label={visible ? "Hide password" : "Show password"}
          onClick={() => setVisible((v) => !v)}
          className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
        >
          {visible ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
        </button>
      </div>

      {showStrength && value ? (
        <div className="mt-2 space-y-2">
          <div className="flex items-center gap-2">
            <div className="flex h-1.5 flex-1 gap-1">
              {[1, 2, 3, 4].map((bar) => (
                <div
                  key={bar}
                  className={cn(
                    "flex-1 rounded-full transition-colors",
                    strength.score >= bar ? strength.color : "bg-gray-200"
                  )}
                />
              ))}
            </div>
            <span className="w-16 text-right text-xs font-medium text-gray-600">
              {strength.label}
            </span>
          </div>
          <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {strength.checks.map((check) => (
              <li key={check.key} className="flex items-center gap-1.5 text-xs">
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    check.met ? "bg-green-500" : "bg-gray-300"
                  )}
                />
                <span className={check.met ? "text-gray-700" : "text-gray-400"}>
                  {check.label}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}