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
    <div className="min-h-screen bg-background text-foreground flex">
      {/* Sidebar */}
      <aside className="hidden border-r border-border-default bg-surface-1 md:fixed md:inset-y-0 md:left-0 md:flex md:w-64 md:flex-col">
        <div className="flex h-16 items-center px-6">
          <BrandLogo />
        </div>
        <nav aria-label="Application navigation" className="flex-1 space-y-1 px-4 py-4">
          {appLinks.map((link) => {
            const isActive = pathname.startsWith(link.href) && (link.href !== "/explore" || pathname === "/explore");
            return (
              <Link
                className={[
                  "flex h-10 items-center rounded-lg px-3 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-surface-2 text-foreground"
                    : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
                ].join(" ")}
                href={link.href}
                key={link.href}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Main Content Area */}
      <div className="flex w-full flex-col md:ml-64">
        {/* Desktop Header */}
        <header className="sticky top-0 z-30 hidden h-16 items-center justify-between border-b border-border-default bg-background/95 px-6 backdrop-blur-md md:flex">
          <nav className="flex items-center gap-6">
            <Link href="/explore" className="text-sm font-medium text-foreground">
              Frameworks
            </Link>
            <Link href="/projects" className="text-sm font-medium text-foreground-muted hover:text-foreground transition-colors">
              Projects
            </Link>
            <Link href="/contributors" className="text-sm font-medium text-foreground-muted hover:text-foreground transition-colors">
              Contributors
            </Link>
            <Link href="/collections" className="text-sm font-medium text-foreground-muted hover:text-foreground transition-colors">
              Collections
            </Link>
          </nav>
          
          <div className="flex items-center gap-4">
            <div className="relative w-64">
              <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input 
                type="text" 
                placeholder="Search frameworks, projects..." 
                className="h-9 w-full rounded-lg border border-border-default bg-surface-2 pl-9 pr-4 text-sm text-foreground placeholder:text-foreground-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent transition-colors"
              />
            </div>
            <ThemeToggle />
            <button className="flex h-9 w-9 items-center justify-center rounded-lg border border-border-default text-foreground-muted hover:bg-surface-2 transition-colors">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </button>
            <button className="flex h-9 items-center gap-2 rounded-lg border border-border-default px-3 text-sm font-medium text-foreground hover:bg-surface-2 transition-colors">
              <div className="h-5 w-5 rounded-full bg-surface-3 flex items-center justify-center">
                <svg className="h-3 w-3 text-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>
              Account
              <svg className="h-3 w-3 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>
        </header>

        {/* Mobile Header */}
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border-default bg-background/95 px-4 backdrop-blur-md md:hidden">
          <BrandLogo className="h-6 w-24" />
          <nav
            aria-label="Mobile application navigation"
            className="flex flex-1 items-center gap-2 overflow-x-auto px-4"
          >
            {appLinks.map((link) => (
              <Link
                className={[
                  "whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  pathname.startsWith(link.href) && (link.href !== "/explore" || pathname === "/explore")
                    ? "bg-surface-2 text-foreground"
                    : "text-foreground-muted",
                ].join(" ")}
                href={link.href}
                key={link.href}
              >
                {link.label}
              </Link>
            ))}
          </nav>
          <ThemeToggle />
        </header>

        {/* Page Content */}
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
