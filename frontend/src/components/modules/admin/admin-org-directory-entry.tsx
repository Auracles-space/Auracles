"use client";

/**
 * One organization in the admin directory, in both responsive layouts.
 *
 * Below `md` each organization is a stacked card with full-width 44px+
 * actions so admins can moderate from a phone without horizontal scrolling;
 * from `md` up the same data renders as a table row. Both variants share the
 * pills, the suspension/closure note, and the action set so the two layouts
 * can never drift apart. The organization name links to its admin detail page.
 *
 * Maps to: organizations end-to-end design, Slice D (directory) and Decision 4.
 */
import Link from "next/link";

import type { AdminOrgResponse } from "@/lib/generated/types.gen";
import { formatShortDate } from "@/lib/marketplace/format";
import { Button } from "@/components/ui/button";
import { StatusPill, describeStatus, ownerStatusKey } from "@/components/ui/status-pill";
import {
  CAPABILITY_LABELS,
  type OrgCapability,
} from "@/components/modules/admin/org-capability-controls";

/** Directory-level actions an admin can start from a row or card. */
export type OrgDirectoryAction = "suspend" | "reinstate" | "reactivate";

type EntryProps = {
  /** Organization to render. */
  org: AdminOrgResponse;
  /** Open the confirm dialog for a lifecycle action. */
  onAction: (org: AdminOrgResponse, kind: OrgDirectoryAction) => void;
  /** Open the per-capability dialog. */
  onCapabilities: (org: AdminOrgResponse) => void;
};

/** Resolve the lifecycle status key; closure outranks suspension. */
function lifecycleKey(org: AdminOrgResponse): "active" | "suspended" | "deactivated" {
  if (org.deactivated_at) return "deactivated";
  if (org.suspended_at) return "suspended";
  return "active";
}

/**
 * Organization name linking to its admin detail page.
 *
 * @param org - Organization to link to.
 */
function OrgNameLink({ org }: { org: AdminOrgResponse }) {
  return (
    <Link
      className="break-words font-semibold text-foreground underline-offset-4 hover:text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      href={`/admin/organizations/${org.id}`}
    >
      {org.name}
    </Link>
  );
}

/**
 * Lifecycle and KYB pills for an organization.
 *
 * @param org - Organization whose status and verification state to show.
 */
function StatusPills({ org }: { org: AdminOrgResponse }) {
  return (
    <div className="flex flex-wrap gap-1">
      <StatusPill status={lifecycleKey(org)} />
      <StatusPill status={ownerStatusKey(org.kyb_status ?? "unverified", "kyb")} />
    </div>
  );
}

/**
 * When and why a suspended or closed organization lost access, if it did.
 *
 * @param org - Organization to describe.
 */
function LifecycleNote({ org }: { org: AdminOrgResponse }) {
  const closed = !!org.deactivated_at;
  if (!closed && !org.suspended_at) return null;
  const label = closed
    ? `Closed ${formatShortDate(org.deactivated_at)}`
    : `Suspended ${formatShortDate(org.suspended_at)}`;
  const reason = closed ? org.deactivation_reason : org.suspension_reason;
  return (
    <div className="mt-1 grid gap-0.5 text-xs text-foreground-muted">
      <p className="font-medium">{label}</p>
      {reason ? <p className="break-words">{reason}</p> : null}
    </div>
  );
}

/**
 * One pill per capability, naming the capability and its state.
 *
 * @param org - Organization whose capabilities to list.
 */
function CapabilityPills({ org }: { org: AdminOrgResponse }) {
  const entries = Object.entries(org.capabilities);
  if (entries.length === 0) {
    return <span className="text-xs text-foreground-muted">No capabilities</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([cap, state]) => (
        <StatusPill
          key={cap}
          label={`${CAPABILITY_LABELS[cap as OrgCapability] ?? cap} ${describeStatus(state).label.toLowerCase()}`}
          status={state}
        />
      ))}
    </div>
  );
}

/**
 * Capabilities plus the one lifecycle action that applies to the org's state.
 *
 * Closed organizations can only be reactivated; capabilities and suspend stay
 * disabled until they are reopened.
 *
 * @param props - Organization, handlers, and extra button classes.
 */
function Actions({ org, onAction, onCapabilities, buttonClassName = "" }: EntryProps & { buttonClassName?: string }) {
  const closed = !!org.deactivated_at;
  const suspended = !!org.suspended_at;
  return (
    <>
      <Button className={buttonClassName} disabled={closed} onClick={() => onCapabilities(org)} variant="secondary">
        Capabilities
      </Button>
      {suspended && !closed ? (
        <Button className={buttonClassName} onClick={() => onAction(org, "reinstate")} variant="secondary">
          Reinstate
        </Button>
      ) : (
        <Button className={buttonClassName} disabled={suspended || closed} onClick={() => onAction(org, "suspend")} variant="secondary">
          Suspend
        </Button>
      )}
      {closed ? (
        <Button className={buttonClassName} onClick={() => onAction(org, "reactivate")} variant="secondary">
          Reactivate
        </Button>
      ) : null}
    </>
  );
}

/**
 * Phone-width card for one organization (rendered inside a `md:hidden` list).
 *
 * @param props - Organization and action handlers.
 */
export function AdminOrgCard(props: EntryProps) {
  const { org } = props;
  return (
    <li className="grid gap-3 rounded-xl border border-border-default bg-surface-2 p-4">
      <div className="min-w-0">
        <p className="flex min-h-11 items-center">
          <OrgNameLink org={org} />
        </p>
        <p className="break-all text-xs text-foreground-muted">@{org.slug}</p>
        <p className="mt-1 text-xs text-foreground-muted">
          {org.country} · {org.member_count} {org.member_count === 1 ? "member" : "members"}
        </p>
        <LifecycleNote org={org} />
      </div>
      <StatusPills org={org} />
      <CapabilityPills org={org} />
      <div className="grid gap-2">
        <Actions {...props} buttonClassName="w-full" />
      </div>
    </li>
  );
}

/**
 * Table row for one organization (md+ layout).
 *
 * @param props - Organization and action handlers.
 */
export function AdminOrgTableRow(props: EntryProps) {
  const { org } = props;
  const status = lifecycleKey(org);
  return (
    <tr className="align-top transition-colors hover:bg-surface-2/50">
      <td className="px-6 py-4">
        <p>
          <OrgNameLink org={org} />
        </p>
        <p className="text-xs text-foreground-muted">@{org.slug}</p>
      </td>
      <td className="px-6 py-4">{org.country}</td>
      <td className="px-6 py-4">{org.member_count}</td>
      <td className="px-6 py-4">
        <CapabilityPills org={org} />
      </td>
      <td className="px-6 py-4">
        <StatusPill status={status} />
        <LifecycleNote org={org} />
      </td>
      <td className="px-6 py-4">
        <StatusPill status={ownerStatusKey(org.kyb_status ?? "unverified", "kyb")} />
      </td>
      <td className="px-6 py-4">
        <div className="flex flex-wrap justify-end gap-2">
          <Actions {...props} />
        </div>
      </td>
    </tr>
  );
}
