"use client";

/**
 * Admin workspace navigation.
 *
 * One list of admin destinations rendered two ways: a persistent sidebar on
 * wide screens, and a drawer behind a Menu button below the sidebar
 * breakpoint so the navigation no longer stacks above every admin page.
 */
import Link from "next/link";
import { Cross1Icon } from "@radix-ui/react-icons";
import { useEffect, useRef, type ReactNode } from "react";

import { StepUpPill } from "@/components/modules/auth/step-up-pill";

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
export const adminGroups: AdminNavGroup[] = [
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
        summary:
          "Monitor payouts and failed transfers, and review bank accounts shared by several owners.",
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
 * Return the label of the admin page a path belongs to, if any.
 *
 * @param pathname - Current path.
 */
export function currentAdminPageLabel(pathname: string): string | null {
  for (const group of adminGroups) {
    for (const link of group.links) {
      if (pathname.startsWith(link.href)) {
        return link.label;
      }
    }
  }
  return null;
}

/**
 * Render the admin workspace introduction card.
 */
export function AdminWorkspaceIntro() {
  return (
    <header className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin workspace
        </p>
        <StepUpPill />
      </div>
      <h1 className="mt-2 font-heading text-2xl font-bold text-foreground">Operations</h1>
      <p className="mt-2 text-sm leading-6 text-foreground-muted">
        Review marketplace health, moderation signals, and sensitive account
        actions from one controlled surface.
      </p>
    </header>
  );
}

/**
 * Render the grouped admin links.
 *
 * @param pathname - Current path, to mark the active link.
 * @param badgeCounts - Items needing attention, keyed by link href.
 * @param onNavigate - Called when a link is chosen (closes the drawer).
 */
export function AdminNavLinks({
  pathname,
  badgeCounts,
  onNavigate,
}: {
  pathname: string;
  badgeCounts: Record<string, number>;
  onNavigate?: () => void;
}) {
  return (
    <div className="grid gap-4">
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
                aria-current={isActive ? "page" : undefined}
                className={[
                  "rounded-xl border px-3 py-2.5 text-left transition-colors",
                  isActive
                    ? "border-accent/40 bg-accent/10 text-foreground"
                    : "border-transparent text-foreground-muted hover:border-border-default hover:bg-surface-2 hover:text-foreground",
                ].join(" ")}
                href={link.href}
                key={link.href}
                onClick={onNavigate}
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
                  <p className="mt-1 text-xs leading-5 text-foreground-muted">{link.summary}</p>
                ) : null}
              </Link>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/**
 * Render the admin navigation drawer for screens narrower than the sidebar.
 *
 * Closes on Escape, on the backdrop, and from its close button; focus moves
 * to the close button on open so keyboard users land inside the drawer.
 *
 * @param open - Whether the drawer is shown.
 * @param onClose - Called to close it.
 * @param children - Drawer content.
 */
export function AdminNavDrawer({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    closeRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 xl:hidden">
      <div aria-hidden="true" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div
        aria-label="Admin navigation"
        aria-modal="true"
        id="admin-nav-drawer"
        className="absolute inset-y-0 left-0 grid w-[min(20rem,88vw)] content-start gap-4 overflow-y-auto border-r border-border-default bg-background p-4 shadow-sm motion-safe:animate-[fade-in_120ms_ease-out]"
        role="dialog"
      >
        <div className="flex justify-end">
          <button
            aria-label="Close menu"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 text-foreground hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            <Cross1Icon aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
