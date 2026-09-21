import Link from "next/link";
import { Landmark } from "lucide-react";

const footerLinks = {
  Platform: [
    { href: "/about", label: "About" },
    { href: "/dashboard", label: "Dashboard" },
    { href: "/report", label: "Report Issue" },
  ],
  Resources: [
    { href: "/docs", label: "Documentation" },
    { href: "/docs/architecture", label: "Architecture" },
  ],
  Legal: [
    { href: "/privacy", label: "Privacy Policy" },
    { href: "/terms", label: "Terms of Service" },
  ],
};

export function Footer() {
  return (
    <footer className="border-t border-white/10 bg-navy-950 text-slate-300">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 sm:py-10">
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <div className="col-span-2 sm:col-span-1">
            <Link href="/" className="mb-3 flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600 text-white">
                <Landmark className="h-4 w-4" />
              </span>
              <span className="text-lg font-semibold tracking-tight text-white">
                CivicAgent
              </span>
            </Link>
            <p className="text-xs text-slate-400 sm:text-sm">
              AI-powered civic governance and citizen engagement.
            </p>
          </div>
          {Object.entries(footerLinks).map(([category, links]) => (
            <div key={category}>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                {category}
              </h3>
              <ul className="space-y-1.5">
                {links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-xs text-slate-400 transition-colors hover:text-white sm:text-sm"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-6 flex flex-col items-center justify-between gap-2 border-t border-white/10 pt-4 text-center sm:flex-row sm:text-left">
          <p className="text-xs text-slate-500 sm:text-sm">
            &copy; {new Date().getFullYear()} CivicAgent. All rights reserved.
          </p>
          <p className="text-[10px] text-slate-600 sm:text-xs">
            AI recommendations are advisory and verified by officials before any decision is taken.
          </p>
        </div>
      </div>
    </footer>
  );
}