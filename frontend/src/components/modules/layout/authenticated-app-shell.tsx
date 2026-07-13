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
import { BrowserSessionGate } from "@/components/modules/layout/browser-session-gate";
import { HeaderSearch } from "@/components/modules/layout/header-search";
import { PendingInvitationsToast } from "@/components/modules/settings/pending-invitations-toast";


type AuthenticatedAppShellProps = {
  children: ReactNode;
  roles: string[];
};

/**
 * Render shared chrome for authenticated application routes.
 *
 * @param props - App route content.
 */
function getNavLinkIcon(label: string) {
  const norm = label.toLowerCase();
  if (norm.includes("explore")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    );
  }
  if (norm.includes("project")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    );
  }
  if (norm.includes("attestation") || norm.includes("attestor")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    );
  }
  if (norm.includes("framework")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
      </svg>
    );
  }
  if (norm.includes("collection")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
      </svg>
    );
  }
  if (norm.includes("financial")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    );
  }
  if (norm.includes("developer")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    );
  }
  if (norm.includes("library")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2" />
      </svg>
    );
  }
  if (norm.includes("search")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
      </svg>
    );
  }
  if (norm.includes("admin")) {
    return (
      <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    );
  }
  return (
    <svg className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

export function AuthenticatedAppShell({
  children,
  roles,
}: AuthenticatedAppShellProps) {
  const pathname = usePathname() ?? "";
  const links = visibleNavLinks(appLinks, roles);

  return (
    <div className="h-screen bg-background text-foreground flex overflow-hidden">
      <PendingInvitationsToast />
      {/* Sidebar */}
      <aside className="hidden bg-background md:fixed md:inset-y-0 md:left-0 md:flex md:w-[260px] md:flex-col z-10">
        <div className="flex h-[72px] items-center px-6">
          <BrandLogo href="/explore" className="h-7 w-[120px]" />
        </div>
        <nav aria-label="Application navigation" className="flex-1 space-y-1.5 px-4 py-6 overflow-y-auto">
          {links.map((link) => {
            const isActive = pathname.startsWith(link.href);
            return (
              <Link
                className={[
                  "flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-surface-1 shadow-[0_2px_8px_-2px_rgba(0,0,0,0.05),0_1px_2px_rgba(0,0,0,0.02)] border border-border-default text-foreground scale-[1.02]"
                    : "text-foreground-muted hover:bg-black/5 dark:hover:bg-white/5 hover:text-foreground",
                ].join(" ")}
                href={link.href}
                key={link.href}
              >
                {getNavLinkIcon(link.label)}
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
            <div className="w-64 xl:w-80 mr-2">
              <HeaderSearch variant="app" placeholder="Search..." />
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
                <div className="absolute right-0 top-12 w-[calc(100vw-2rem)] sm:w-64 rounded-xl border border-border-default bg-surface-1 p-4 shadow-lg z-50 max-h-[calc(100vh-5rem)] overflow-y-auto">
                  <nav className="flex flex-col space-y-2">
                    {links.map((link) => (
                      <Link
                        className={[
                          "rounded-xl px-3 py-2 text-sm font-medium transition-colors flex items-center gap-3",
                          pathname.startsWith(link.href)
                            ? "bg-surface-2 text-foreground"
                            : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
                        ].join(" ")}
                        href={link.href}
                        key={link.href}
                      >
                        {getNavLinkIcon(link.label)}
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
          {/* Mobile search row — desktop header field is hidden on mobile. */}
          <div className="pb-3">
            <HeaderSearch variant="app" placeholder="Search..." />
          </div>
        </header>

        {/* Page Content Container - The Bento Box */}
        <main className="flex-1 bg-surface-1 md:rounded-tl-[32px] md:border-l md:border-t md:border-border-default md:shadow-[-4px_-4px_24px_rgba(0,0,0,0.02)] dark:md:shadow-none overflow-y-auto relative z-20">
          <BrowserSessionGate>{children}</BrowserSessionGate>
        </main>
      </div>
    </div>
  );
}
