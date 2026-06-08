"use client";

/**
 * Authenticated app shell.
 *
 * Provides persistent product navigation for Operator, Contributor, and
 * settings workspaces. Auth enforcement remains in middleware/backend calls.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { BrandLogo } from "@/components/ui/brand-logo";
import { ThemeToggle } from "@/components/ui/theme-toggle";

type AuthenticatedAppShellProps = {
  children: ReactNode;
};

const appLinks = [
  { href: "/explore", label: "Explore" },
  { href: "/dashboard/frameworks", label: "Frameworks" },
  { href: "/projects", label: "Projects" },
  { href: "/attest", label: "Attest" },
  { href: "/financials", label: "Financials" },
  { href: "/settings/account", label: "Settings" },
];

/**
 * Render shared chrome for authenticated application routes.
 *
 * @param props - App route content.
 */
export function AuthenticatedAppShell({ children }: AuthenticatedAppShellProps) {
  const pathname = usePathname() ?? "";

  return (
    <div className="min-h-screen bg-accent text-white flex">
      {/* Sidebar */}
      <aside className="hidden bg-accent md:fixed md:inset-y-0 md:left-0 md:flex md:w-[260px] md:flex-col z-10">
        <div className="flex h-[72px] items-center px-6">
          <BrandLogo className="h-7 w-[120px]" variant="dark" />
        </div>
        <nav aria-label="Application navigation" className="flex-1 space-y-1.5 px-4 py-6">
          {appLinks.map((link) => {
            const isActive = pathname.startsWith(link.href) && (link.href !== "/explore" || pathname === "/explore");
            return (
              <Link
                className={[
                  "flex h-10 items-center rounded-xl px-3 text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-white/20 shadow-sm border border-white/10 text-white scale-[1.02]"
                    : "text-white/70 hover:bg-white/10 hover:text-white",
                ].join(" ")}
                href={link.href}
                key={link.href}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        
        {/* User profile widget at the bottom of the sidebar */}
        <div className="p-4 mt-auto">
          <button className="flex w-full items-center gap-3 rounded-xl p-2 hover:bg-white/10 transition-colors border border-transparent hover:border-white/10 text-left">
            <div className="h-9 w-9 shrink-0 rounded-full bg-white/10 flex items-center justify-center border border-white/20">
              <svg className="h-4 w-4 shrink-0 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate">Account</p>
              <p className="text-xs text-white/60 truncate">Manage settings</p>
            </div>
            <svg className="h-4 w-4 shrink-0 text-white/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
            </svg>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex w-full flex-col md:ml-[260px] min-h-screen text-foreground">
        {/* Desktop Header Container (sits above the bento card) */}
        <header className="sticky top-0 z-30 hidden h-[72px] items-center justify-between bg-accent px-8 md:flex">
          <div className="flex-1" />
          
          <div className="flex items-center gap-3">
            <div className="relative w-64 xl:w-80 mr-2">
              <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/60 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input 
                type="text" 
                placeholder="Search..." 
                className="h-9 w-full rounded-xl border border-white/10 bg-white/10 pl-9 pr-4 text-sm text-white shadow-sm placeholder:text-white/60 focus:border-white/30 focus:bg-white/20 focus:outline-none focus:ring-1 focus:ring-white/30 transition-colors"
              />
            </div>
            <div className="text-white">
              <ThemeToggle />
            </div>
            <button className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/10 shadow-sm text-white/80 hover:bg-white/20 transition-colors">
              <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </button>
          </div>
        </header>

        {/* Mobile Header */}
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-white/10 bg-accent px-4 backdrop-blur-md md:hidden">
          <BrandLogo className="h-7 w-28" variant="dark" />
          <nav
            aria-label="Mobile application navigation"
            className="flex flex-1 items-center gap-2 overflow-x-auto px-4"
          >
            {appLinks.map((link) => {
              const isActive = pathname.startsWith(link.href) && (link.href !== "/explore" || pathname === "/explore");
              return (
                <Link
                  className={[
                    "whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-white/20 text-white"
                      : "text-white/70 hover:bg-white/10 hover:text-white",
                  ].join(" ")}
                  href={link.href}
                  key={link.href}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="text-white">
            <ThemeToggle />
          </div>
        </header>

        {/* Page Content Container - The Bento Box */}
        <main className="flex-1 bg-surface-1 md:rounded-tl-[32px] md:border-l md:border-t md:border-border-default md:shadow-[-4px_-4px_24px_rgba(0,0,0,0.02)] dark:md:shadow-none overflow-hidden relative z-20">
          {children}
        </main>
      </div>
    </div>
  );
}

