"use client";

/**
 * Header of the admin organization detail page: back link, name, public
 * profile link, lifecycle and KYB pills, created date, and a banner naming
 * when, why and by whom a suspended or closed organization lost access.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail), Decision 1.
 */
import { ArrowLeftIcon } from "@radix-ui/react-icons";
import Link from "next/link";

import { lifecycleKey } from "@/components/modules/admin/org-detail/org-detail-helpers";
import { StatusPill, ownerStatusKey } from "@/components/ui/status-pill";
import type { AdminOrgOverviewResponse } from "@/lib/generated/types.gen";
import { formatShortDate } from "@/lib/marketplace/format";

/**
 * Suspension or closure banner; renders nothing for an active organization.
 *
 * @param org - Organization overview.
 */
function LifecycleBanner({ org }: { org: AdminOrgOverviewResponse }) {
  const closed = !!org.deactivated_at;
  if (!closed && !org.suspended_at) return null;
  const title = closed ? "Organization closed" : "Organization suspended";
  const date = formatShortDate(closed ? org.deactivated_at : org.suspended_at);
  const reason = closed ? org.deactivation_reason : org.suspension_reason;
  const actor = closed ? org.deactivated_by : org.suspended_by;
  return (
    <div
      aria-label={title}
      className={`grid gap-1 rounded-xl border p-4 text-sm ${closed ? "border-border-default bg-surface-2 text-foreground" : "border-error/30 bg-error/10 text-foreground"}`}
      role="status"
    >
      <p className={`font-semibold ${closed ? "text-foreground" : "text-error"}`}>
        {closed ? "Closed" : "Suspended"} on {date}
        {actor ? ` by ${actor.display_name}` : ""}
      </p>
      <p className="break-words">{reason ? `Reason: ${reason}` : "No reason recorded."}</p>
    </div>
  );
}

/**
 * Render the detail page header for one organization.
 *
 * @param org - Organization overview from the detail endpoint.
 */
export function OrgDetailHeader({ org }: { org: AdminOrgOverviewResponse }) {
  return (
    <header className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
      <Link
        className="inline-flex min-h-11 w-fit items-center gap-1.5 rounded-md text-sm font-semibold text-accent hover:text-accent/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        href="/admin/organizations"
      >
        <ArrowLeftIcon aria-hidden className="h-4 w-4" />
        All organizations
      </Link>
      <div className="grid gap-2">
        <h1 className="break-words font-heading text-2xl font-bold text-foreground md:text-3xl">{org.name}</h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-foreground-muted">
          <Link
            className="inline-flex min-h-11 items-center break-all font-medium text-accent underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            href={`/orgs/${org.slug}`}
          >
            @{org.slug}
          </Link>
          <span>{org.country}</span>
          <span>Created {formatShortDate(org.created_at)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill status={lifecycleKey(org)} />
          <StatusPill status={ownerStatusKey(org.kyb_status, "kyb")} />
        </div>
      </div>
      <LifecycleBanner org={org} />
    </header>
  );
}
