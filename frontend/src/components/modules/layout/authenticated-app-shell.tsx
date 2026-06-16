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

import { AuthenticatedAccountMenu } from "@/components/modules/layout/authenticated-account-menu";
import { BrandLogo } from "@/components/ui/brand-logo";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { NotificationDropdown } from "@/components/modules/layout/notification-dropdown";
import { appLinks, visibleNavLinks } from "@/components/modules/layout/app-navigation";

type AuthenticatedAppShellProps = {
  children: ReactNode;
  roles: string[];
};

/**
 * Render shared chrome for authenticated application routes.
 *
 * @param props - App route content.
 */
export function AuthenticatedAppShell({
  children,
  roles,
}: AuthenticatedAppShellProps) {
  const pathname = usePathname() ?? "";
  const links = visibleNavLinks(appLinks, roles);

  return (
    <div className="h-screen bg-background text-foreground flex overflow-hidden">
      {/* Sidebar */}
      <aside className="hidden bg-background md:fixed md:inset-y-0 md:left-0 md:flex md:w-[260px] md:flex-col z-10">
        <div className="flex h-[72px] items-center px-6">
          <BrandLogo href="/explore" className="h-7 w-[120px]" />
        </div>
        <nav aria-label="Application navigation" className="flex-1 space-y-1.5 px-4 py-6">
          {links.map((link) => {
            const isActive = pathname.startsWith(link.href) && (link.href !== "/explore" || pathname === "/explore");
            return (
              <Link
                className={[
                  "flex h-10 items-center rounded-xl px-3 text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-surface-1 shadow-[0_2px_8px_-2px_rgba(0,0,0,0.05),0_1px_2px_rgba(0,0,0,0.02)] border border-border-default text-foreground scale-[1.02]"
                    : "text-foreground-muted hover:bg-black/5 dark:hover:bg-white/5 hover:text-foreground",
                ].join(" ")}
                href={link.href}
                key={link.href}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        
        <div className="p-4 mt-auto">
          <AuthenticatedAccountMenu roles={roles} />
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex w-full flex-col md:ml-[260px] md:w-[calc(100%-260px)] h-screen">
        {/* Desktop Header Container (sits above the bento card) */}
        <header className="shrink-0 sticky top-0 z-30 hidden h-[72px] items-center justify-between bg-background px-8 md:flex">
          <div className="flex-1" />
          
          <div className="flex items-center gap-3">
            <div className="relative w-64 xl:w-80 mr-2">
              <svg className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input 
                type="text" 
                placeholder="Search..." 
                className="h-10 w-full rounded-xl border border-border-default bg-surface-1 pl-9 pr-4 text-sm text-foreground shadow-sm placeholder:text-foreground-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent transition-colors"
              />
            </div>
            <ThemeToggle />
            <NotificationDropdown />
          </div>
        </header>

        {/* Mobile Header & Drawer */}
        <header className="sticky top-0 z-30 flex flex-col border-b border-border-default bg-background/95 px-4 backdrop-blur-md md:hidden">
          <div className="flex h-16 items-center justify-between">
            <BrandLogo href="/explore" className="h-7 w-28" />
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <NotificationDropdown />
              {/* Native HTML details/summary for simple zero-JS mobile menu */}
              <details className="group relative">
                <summary className="flex h-10 w-10 cursor-pointer list-none items-center justify-center rounded-xl border border-border-default outline-none transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent [&::-webkit-details-marker]:hidden">
                  <svg className="h-5 w-5 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" className="group-open:hidden" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" className="hidden group-open:block" />
                  </svg>
                </summary>
                <div className="absolute right-0 top-12 w-[calc(100vw-2rem)] sm:w-64 rounded-xl border border-border-default bg-surface-1 p-4 shadow-lg z-50">
                  <nav className="flex flex-col space-y-2">
                    {links.map((link) => (
                      <Link
                        className={[
                          "rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                          pathname.startsWith(link.href) && (link.href !== "/explore" || pathname === "/explore")
                            ? "bg-surface-2 text-foreground"
                            : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
                        ].join(" ")}
                        href={link.href}
                        key={link.href}
                      >
                        {link.label}
                      </Link>
                    ))}
                    <div className="my-2 h-px bg-border-default" />
                    <AuthenticatedAccountMenu roles={roles} />
                  </nav>
                </div>
              </details>
            </div>
          </div>
        </header>

        {/* Page Content Container - The Bento Box */}
        <main className="flex-1 bg-surface-1 md:rounded-tl-[32px] md:border-l md:border-t md:border-border-default md:shadow-[-4px_-4px_24px_rgba(0,0,0,0.02)] dark:md:shadow-none overflow-y-auto relative z-20">
          {children}
        </main>
      </div>
    </div>
  );
}
