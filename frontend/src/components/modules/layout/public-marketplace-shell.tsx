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
  { href: "/explore", label: "Frameworks" },
  { href: "/projects", label: "Projects" },
  { href: "/contributors", label: "Contributors" },
  { href: "/collections", label: "Collections" },
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
          <div className="flex items-center gap-8 flex-1">
            <BrandLogo className="h-6 w-24" />
            <nav
              aria-label="Public marketplace navigation"
              className="hidden items-center gap-6 md:flex"
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
            
            <div className="hidden flex-1 max-w-md ml-auto mr-4 md:block">
              <div className="relative w-full">
                <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input 
                  type="text" 
                  placeholder="Search frameworks, projects..." 
                  className="h-9 w-full rounded-lg border border-border-default bg-surface-2 pl-9 pr-4 text-sm text-foreground placeholder:text-foreground-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent transition-colors"
                />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden items-center gap-2 md:flex">
              <ThemeToggle />
              <Link
                className="inline-flex h-9 items-center justify-center rounded-lg px-4 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground"
                href="/login"
              >
                Log in
              </Link>
              <Link
                className="inline-flex h-9 items-center justify-center rounded-lg bg-foreground px-4 text-sm font-medium text-background transition hover:bg-foreground/90"
                href="/register"
              >
                Sign up
              </Link>
            </div>
            {/* Mobile menu could go here */}
          </div>
        </div>
      </header>
      <div className="flex-1">
        {children}
      </div>
    </div>
  );
}
