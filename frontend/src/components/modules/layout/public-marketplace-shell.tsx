/**
 * Public marketplace shell.
 *
 * Gives Explore and public Framework detail pages the same Auracles navigation
 * frame as the rest of the public product instead of rendering as isolated
 * standalone pages.
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandLogo } from "@/components/ui/brand-logo";
import { ThemeToggle } from "@/components/ui/theme-toggle";

type PublicMarketplaceShellProps = {
  children: ReactNode;
};

const topLinks = [
  { href: "/explore", label: "Explore" },
];

/**
 * Render shared chrome for public marketplace routes.
 *
 * @param props - Route content rendered below the public navigation.
 */
export function PublicMarketplaceShell({ children }: PublicMarketplaceShellProps) {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="sticky top-0 z-30 border-b border-border-default bg-background/95 backdrop-blur-md">
        <div className="mx-auto flex h-16 w-full items-center justify-between px-4 md:px-6">
          <div className="flex items-center gap-4 lg:gap-8 flex-1 min-w-0">
            <BrandLogo className="h-6 w-24 shrink-0" />
            <nav
              aria-label="Public marketplace navigation"
              className="hidden items-center gap-4 lg:gap-6 lg:flex shrink-0"
            >
              {topLinks.map((link) => (
                <Link
                  className="text-sm font-medium text-foreground-muted transition hover:text-foreground"
                  href={link.href}
                  key={link.label}
                >
                  {link.label}
                </Link>
              ))}
            </nav>
            
            <div className="hidden flex-1 max-w-md ml-auto mr-4 md:block min-w-0">
              <div className="relative w-full">
                <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input 
                  type="text" 
                  placeholder="Search frameworks, projects..." 
                  className="h-9 w-full rounded-xl border border-border-default bg-surface-2 pl-9 pr-4 text-sm text-foreground placeholder:text-foreground-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent transition-colors"
                />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden items-center gap-2 md:flex">
              <ThemeToggle />
              <Link
                className="inline-flex h-9 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-medium text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-surface-2"
                href="/dashboard/frameworks/new"
              >
                Create Framework
              </Link>
              <div className="mx-1 h-4 w-px bg-border-default" />
              <Link
                className="inline-flex h-9 items-center justify-center rounded-xl px-4 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground"
                href="/login"
              >
                Log in
              </Link>
              <Link
                className="inline-flex h-9 items-center justify-center rounded-xl bg-foreground px-4 text-sm font-medium text-background transition hover:bg-foreground/90"
                href="/register"
              >
                Sign up
              </Link>
            </div>
            {/* Mobile menu (Hamburger details/summary) */}
            <div className="flex items-center gap-2 md:hidden">
              <ThemeToggle />
              <details className="group relative">
                <summary className="flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-xl border border-border-default hover:bg-surface-2 transition-colors [&::-webkit-details-marker]:hidden">
                  <svg className="h-5 w-5 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" className="group-open:hidden" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" className="hidden group-open:block" />
                  </svg>
                </summary>
                <div className="absolute right-0 top-12 w-64 rounded-xl border border-border-default bg-surface-1 p-4 shadow-lg z-50">
                  <nav className="flex flex-col space-y-2">
                    {topLinks.map((link) => (
                      <Link
                        className="rounded-xl px-3 py-2 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground"
                        href={link.href}
                        key={link.label}
                      >
                        {link.label}
                      </Link>
                    ))}
                    <div className="my-2 h-px bg-border-default" />
                    <Link
                      className="rounded-xl border border-border-default bg-surface-1 px-3 py-2 text-sm font-medium text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-surface-2"
                      href="/dashboard/frameworks/new"
                    >
                      New Framework
                    </Link>
                    <div className="my-2 h-px bg-border-default" />
                    <Link
                      className="rounded-xl px-3 py-2 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground"
                      href="/login"
                    >
                      Log in
                    </Link>
                    <Link
                      className="rounded-xl px-3 py-2 text-sm font-medium text-accent transition hover:bg-surface-2"
                      href="/register"
                    >
                      Sign up
                    </Link>
                  </nav>
                </div>
              </details>
            </div>
          </div>
        </div>
      </header>
      <div className="flex-1">
        {children}
      </div>
    </div>
  );
}
