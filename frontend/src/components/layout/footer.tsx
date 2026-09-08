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
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          <div className="col-span-2 md:col-span-1">
            <Link href="/" className="flex items-center gap-2 mb-4">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600 text-white">
                <Landmark className="h-4 w-4" />
              </span>
              <span className="text-lg font-semibold tracking-tight text-white">
                CivicAgent
              </span>
            </Link>
            <p className="text-sm text-slate-400 max-w-xs">
              Building smarter cities through AI-powered civic governance and citizen engagement.
            </p>
          </div>
          {Object.entries(footerLinks).map(([category, links]) => (
            <div key={category}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
                {category}
              </h3>
              <ul className="space-y-2">
                {links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-slate-400 hover:text-white transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-10 border-t border-white/10 pt-8 flex flex-col items-center justify-between gap-2 sm:flex-row">
          <p className="text-sm text-slate-500">
            &copy; {new Date().getFullYear()} CivicAgent. All rights reserved.
          </p>
          <p className="text-xs text-slate-600">
            AI recommendations are advisory and verified by officials before any decision is taken.
          </p>
        </div>
      </div>
    </footer>
  );
}