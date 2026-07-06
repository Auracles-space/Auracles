"use client";

/**
 * Settings workspace navigation shell.
 *
 * Provides a unified local navigation layout for Settings pages (Profile, Account,
 * Notifications, Credentials, Attestor Application, Sessions, Consent, KYC) while
 * preserving visual consistency with the platform admin shells.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, type ReactNode } from "react";

type SettingsWorkspaceShellProps = {
  children: ReactNode;
};

type SettingsLink = {
  href: string;
  label: string;
  getSummary: () => string;
};

const settingsLinks: SettingsLink[] = [
  {
    href: "/settings/identity",
    label: "Identity & Verification",
    getSummary: () => "Private credentials, email verification, and KYC status.",
  },
  {
    href: "/settings/account",
    label: "Account & Security",
    getSummary: () => "Security, password, and GDPR controls.",
  },
  {
    href: "/settings/notifications",
    label: "Notifications",
    getSummary: () => "Choose which events trigger email or in-app alerts.",
  },
  {
    href: "/settings/credentials",
    label: "Professional Credentials",
    getSummary: () => "Verify professional credentials for reviews.",
  },
  {
    href: "/settings/sessions",
    label: "Active Sessions",
    getSummary: () => "Manage active devices and connected sessions.",
  },
  {
    href: "/settings/consent",
    label: "Consent History",
    getSummary: () => "Review your history of legal term agreements.",
  },
  {
    href: "/settings/integrations",
    label: "Connected Accounts",
    getSummary: () => "Manage third-party integrations like Google Drive.",
  },
  {
    href: "/settings/kyc",
    label: "Identity Verification",
    getSummary: () => "Verify your identity to unlock payouts and publishing.",
  },
];

export function SettingsWorkspaceShell({ children }: SettingsWorkspaceShellProps) {
  const pathname = usePathname() ?? "";

  const visibleLinks = useMemo(() => {
    return settingsLinks;
  }, []);

  return (
    <section className="px-4 py-6 text-foreground md:px-8 md:py-8">
      <div className="mx-auto grid max-w-[1280px] gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* Desktop Sidebar Navigation */}
        <aside className="hidden lg:grid content-start gap-4">
          <header className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Settings
            </p>
            <h1 className="mt-2 font-heading text-2xl font-bold text-foreground">
              Preferences
            </h1>
            <p className="mt-2 text-sm leading-6 text-foreground-muted">
              Configure your profile identity, security policies, and application settings.
            </p>
          </header>

          <nav
            aria-label="Settings navigation"
            className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm"
          >
            {visibleLinks.map((link) => {
              const isActive = pathname.startsWith(link.href);
              return (
                <Link
                  className={[
                    "rounded-xl border px-3.5 py-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    isActive
                      ? "border-accent/40 bg-accent/10 text-foreground"
                      : "border-transparent text-foreground-muted hover:border-border-default hover:bg-surface-2 hover:text-foreground",
                  ].join(" ")}
                  href={link.href}
                  key={link.href}
                >
                  <p className="text-sm font-semibold">{link.label}</p>
                  <p className="mt-1 text-xs leading-5 text-foreground-muted">
                    {link.getSummary()}
                  </p>
                </Link>
              );
            })}
          </nav>
        </aside>

        {/* Mobile Horizontal Scrolling Tabs */}
        <div className="lg:hidden">
          <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-none">
            {visibleLinks.map((link) => {
              const isActive = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={[
                    "shrink-0 flex items-center px-4 py-2.5 text-xs font-semibold rounded-xl transition border outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    isActive
                      ? "bg-foreground text-background border-transparent"
                      : "text-foreground-muted bg-surface-1 border-border-default hover:bg-surface-2",
                  ].join(" ")}
                >
                  {link.label}
                </Link>
              );
            })}
          </div>
        </div>

        {/* Main Content Area */}
        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}
