"use client";

/**
 * Admin workspace shell.
 *
 * Provides focused local navigation for `/admin/*` routes while preserving the
 * shared authenticated product chrome outside the admin workspace.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  adminListOrgsV1AdminOrgsGet,
  listAdminAttestationDisputes,
  listAdminAttestations,
  listAdminProjectDisputes,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";
import {
  NEEDS_ADMIN_CHANGED_EVENT,
  ORG_VERIFICATION_CHANGED_EVENT,
} from "@/components/modules/admin/admin-events";
import { StepUpPill } from "@/components/modules/auth/step-up-pill";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";

type AdminWorkspaceShellProps = {
  children: ReactNode;
};

type AdminLink = {
  href: string;
  label: string;
  summary: string;
};

type AdminNavGroup = {
  title: string;
  links: AdminLink[];
};

/**
 * Admin navigation grouped by what the admin is doing: running the
 * marketplace, deciding trust, moving money, or operating the platform.
 */
const adminGroups: AdminNavGroup[] = [
  {
    title: "Marketplace",
    links: [
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
        href: "/admin/invoices",
        label: "Invoices",
        summary: "Review issued invoices for financial reconciliation.",
      },
    ],
  },
  {
    title: "Trust",
    links: [
      {
        href: "/admin/organizations",
        label: "Organizations",
        summary: "Verify businesses, search organizations, suspend or reinstate.",
      },
      {
        href: "/admin/attestors",
        label: "Attestors",
        summary: "Applications, calibration trials, and fixtures in one pipeline.",
      },
      {
        href: "/admin/attestations",
        label: "Attestations",
        summary: "Assign or refund requests matching could not staff.",
      },
      {
        href: "/admin/credentials",
        label: "Credentials",
        summary: "Review evidence and verify or reject submitted credentials.",
      },
      {
        href: "/admin/disputes",
        label: "Disputes",
        summary: "Resolve Attestation and Project disputes with escrow outcomes.",
      },
    ],
  },
  {
    title: "Money",
    links: [
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
        href: "/admin/treasury",
        label: "Treasury",
        summary: "Platform money vs users' money, withdrawals, and monthly statements.",
      },
    ],
  },
  {
    title: "Platform",
    links: [
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
        href: "/admin/developer",
        label: "Developer",
        summary: "Approve or reject Developer Platform applications.",
      },
      {
        href: "/admin/configuration",
        label: "Configuration",
        summary: "Commission, fees, SLAs, and reputation tuning (super-admin).",
      },
    ],
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
  const [attestorCount, setAttestorCount] = useState(0);
  const [disputeCount, setDisputeCount] = useState(0);
  const [pendingOrgCount, setPendingOrgCount] = useState(0);

  const refreshCounts = useCallback(() => {
    async function loadNeedsAdminCount() {
      configureBrowserClient();
      // The count is a badge, not the page. A failed request leaves it at zero
      // rather than rejecting: this shell wraps every admin route, so an
      // uncaught rejection here lands on screens unrelated to attestations.
      let result;
      try {
        result = await listAdminAttestations({
          headers: getAccessTokenHeaders(),
          query: { status: "needs_admin" },
        });
      } catch {
        return;
      }
      if (result.response.ok && result.data) {
        setNeedsAdminCount(result.data.attestations.length);
      }
    }
    async function loadTrustCounts() {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      try {
        const [applications, attestationDisputes, projectDisputes] = await Promise.all([
          listOrgAttestorApplicationsForAdmin({ headers, query: { status: "submitted" } }),
          listAdminAttestationDisputes({ headers, query: { status: "active" } }),
          listAdminProjectDisputes({ headers }),
        ]);
        if (applications.response.ok && applications.data) {
          setAttestorCount(applications.data.applications.length);
        }
        const open =
          (attestationDisputes.response.ok && attestationDisputes.data
            ? attestationDisputes.data.disputes.length
            : 0) +
          (projectDisputes.response.ok && projectDisputes.data
            ? projectDisputes.data.disputes.filter((dispute: { status: string }) => dispute.status !== "resolved")
                .length
            : 0);
        setDisputeCount(open);
      } catch {
        return;
      }
    }
    async function loadPendingOrgCount() {
      configureBrowserClient();
      // One row is enough: the badge reads the total, and a failure leaves it
      // at zero for the same reason as the needs-admin count above.
      try {
        const result = await adminListOrgsV1AdminOrgsGet({
          headers: getAccessTokenHeaders(),
          query: { kyb_status: "pending", page: 1, page_size: 1 },
        });
        if (result.response.ok && result.data) {
          setPendingOrgCount(result.data.total);
        }
      } catch {
        return;
      }
    }
    void loadNeedsAdminCount();
    void loadTrustCounts();
    void loadPendingOrgCount();
  }, []);

  useEffect(() => {
    refreshCounts();
  }, [refreshCounts]);
  // Badges otherwise load once, so work submitted while an admin page is open
  // (an attestor application, a dispute) showed no count until a reload.
  useRefetchOnFocus(refreshCounts);

  useEffect(() => {
    const onChanged = () => refreshCounts();
    const onOrgVerificationChanged = () => refreshCounts();
    window.addEventListener(NEEDS_ADMIN_CHANGED_EVENT, onChanged);
    window.addEventListener(ORG_VERIFICATION_CHANGED_EVENT, onOrgVerificationChanged);
    return () => {
      window.removeEventListener(NEEDS_ADMIN_CHANGED_EVENT, onChanged);
      window.removeEventListener(ORG_VERIFICATION_CHANGED_EVENT, onOrgVerificationChanged);
    };
  }, [refreshCounts]);

  const badgeCounts: Record<string, number> = {
    "/admin/attestations": needsAdminCount,
    "/admin/attestors": attestorCount,
    "/admin/disputes": disputeCount,
    "/admin/organizations": pendingOrgCount,
  };

  return (
    <section className="px-4 py-6 text-foreground md:px-8 md:py-8">
      <div className="mx-auto grid max-w-[1280px] gap-6 xl:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="grid content-start gap-4">
          <header className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                Admin workspace
              </p>
              <StepUpPill />
            </div>
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
            className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm"
          >
            {adminGroups.map((group) => (
              <div className="grid gap-1" key={group.title}>
                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-foreground-muted">
                  {group.title}
                </p>
                {group.links.map((link) => {
                  const isActive = pathname.startsWith(link.href);
                  const badge = badgeCounts[link.href] ?? 0;
                  return (
                    <Link
                      className={[
                        "rounded-xl border px-3 py-2.5 text-left transition-colors",
                        isActive
                          ? "border-accent/40 bg-accent/10 text-foreground"
                          : "border-transparent text-foreground-muted hover:border-border-default hover:bg-surface-2 hover:text-foreground",
                      ].join(" ")}
                      href={link.href}
                      key={link.href}
                      title={link.summary}
                    >
                      <p className="flex items-center justify-between gap-2 text-sm font-semibold">
                        {link.label}
                        {badge > 0 ? (
                          <span
                            aria-label={`${badge} needing attention`}
                            className="inline-flex min-w-5 items-center justify-center rounded-badge bg-accent px-1.5 text-xs font-bold text-background"
                          >
                            {badge}
                          </span>
                        ) : null}
                      </p>
                      {isActive ? (
                        <p className="mt-1 text-xs leading-5 text-foreground-muted">
                          {link.summary}
                        </p>
                      ) : null}
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>
        </aside>

        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}
