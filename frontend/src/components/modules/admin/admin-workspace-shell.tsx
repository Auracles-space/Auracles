"use client";

/**
 * Admin workspace shell.
 *
 * Provides focused local navigation for `/admin/*` routes while preserving the
 * shared authenticated product chrome outside the admin workspace.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listAdminAttestations } from "@/lib/generated/sdk.gen";
import { NEEDS_ADMIN_CHANGED_EVENT } from "@/components/modules/admin/admin-events";

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
    href: "/admin/money",
    label: "Money",
    summary: "Trace payments, escrow, webhooks, and audit history end to end.",
  },
  {
    href: "/admin/payouts",
    label: "Payouts",
    summary: "Monitor Contributor and Organization payouts and failed transfers.",
  },
  {
    href: "/admin/gdpr",
    label: "GDPR",
    summary: "Review account-deletion and data-export requests and blockers.",
  },
  {
    href: "/admin/connectors",
    label: "Connectors",
    summary: "Audit external file-provider connections and revocation state.",
  },
  {
    href: "/admin/waitlist",
    label: "Waitlist",
    summary: "Review pre-launch signups and demand by source.",
  },
  {
    href: "/admin/invoices",
    label: "Invoices",
    summary: "Review issued invoices for financial reconciliation.",
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
    href: "/admin/organizations",
    label: "Organizations",
    summary: "Search organizations and review membership and capabilities.",
  },
  {
    href: "/admin/org-attestors",
    label: "Org Attestors",
    summary: "Review applications and verify KYB for organization attestors.",
  },
  {
    href: "/admin/calibration-fixtures",
    label: "Calibration Fixtures",
    summary: "Manage attestor-trial fixtures: artifacts, scans, and answer keys.",
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
  const [needsAdminCount, setNeedsAdminCount] = useState(0);

  useEffect(() => {
    async function loadNeedsAdminCount() {
      configureBrowserClient();
      const result = await listAdminAttestations({
        headers: getAccessTokenHeaders(),
        query: { status: "needs_admin" },
      });
      if (result.response.ok && result.data) {
        setNeedsAdminCount(result.data.attestations.length);
      }
    }
    void loadNeedsAdminCount();
    // Refresh the badge when an admin assigns or refunds a needs-admin request
    // elsewhere in the workspace, so the count never goes stale.
    const onChanged = () => void loadNeedsAdminCount();
    window.addEventListener(NEEDS_ADMIN_CHANGED_EVENT, onChanged);
    return () =>
      window.removeEventListener(NEEDS_ADMIN_CHANGED_EVENT, onChanged);
  }, []);

  const badgeCounts: Record<string, number> = {
    "/admin/attestations": needsAdminCount,
  };

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
              const badge = badgeCounts[link.href] ?? 0;
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
                  <p className="flex items-center justify-between gap-2 text-sm font-semibold">
                    {link.label}
                    {badge > 0 ? (
                      <span
                        aria-label={`${badge} needing attention`}
                        className="inline-flex min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-xs font-bold text-background"
                      >
                        {badge}
                      </span>
                    ) : null}
                  </p>
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
