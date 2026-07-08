"use client";

/**
 * Admin workspace shell.
 *
 * Provides focused local navigation for `/admin/*` routes while preserving the
 * shared authenticated product chrome outside the admin workspace.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

type AdminWorkspaceShellProps = {
  children: ReactNode;
};

const adminLinks = [
  {
    href: "/admin/analytics",
    label: "Analytics",
    summary: "GMV, activity, and frozen daily trend history.",
  },
  {
    href: "/admin/moderation",
    label: "Moderation",
    summary: "Rarity, near-duplicate, and PII review signals.",
  },
  {
    href: "/admin/users",
    label: "Users",
    summary: "Search accounts and apply suspension controls.",
  },
  {
    href: "/admin/disputes",
    label: "Disputes",
    summary: "Resolve Project milestone disputes with escrow outcomes.",
  },
  {
    href: "/admin/attestations",
    label: "Attestations",
    summary: "Assign, refund, and resolve attestation workflows.",
  },
  {
    href: "/admin/credentials",
    label: "Credentials",
    summary: "Review evidence and verify or reject submitted credentials.",
  },
  {
    href: "/admin/org-attestors",
    label: "Org Attestors",
    summary: "Review applications and verify KYB for organization attestors.",
  },
  {
    href: "/admin/developer",
    label: "Developer",
    summary: "Approve or reject Developer Platform applications.",
  },
  {
    href: "/admin/configuration",
    label: "Configuration",
    summary: "Commission, fees, SLAs, and reputation tuning (super-admin).",
  },
];

/**
 * Render the local admin navigation and nested admin page content.
 *
 * @param props - Nested admin route content.
 */
export function AdminWorkspaceShell({ children }: AdminWorkspaceShellProps) {
  const pathname = usePathname() ?? "";

  return (
    <section className="px-4 py-6 text-foreground md:px-8 md:py-8">
      <div className="mx-auto grid max-w-[1280px] gap-6 xl:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="grid content-start gap-4">
          <header className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Admin workspace
            </p>
            <h1 className="mt-2 font-heading text-2xl font-bold text-foreground">
              Operations
            </h1>
            <p className="mt-2 text-sm leading-6 text-foreground-muted">
              Review marketplace health, moderation signals, and sensitive account
              actions from one controlled surface.
            </p>
          </header>

          <nav
            aria-label="Admin navigation"
            className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm"
          >
            {adminLinks.map((link) => {
              const isActive = pathname.startsWith(link.href);
              return (
                <Link
                  className={[
                    "rounded-xl border px-3 py-3 text-left transition-colors",
                    isActive
                      ? "border-accent/40 bg-accent/10 text-foreground"
                      : "border-transparent text-foreground-muted hover:border-border-default hover:bg-surface-2 hover:text-foreground",
                  ].join(" ")}
                  href={link.href}
                  key={link.href}
                >
                  <p className="text-sm font-semibold">{link.label}</p>
                  <p className="mt-1 text-xs leading-5 text-foreground-muted">
                    {link.summary}
                  </p>
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}
