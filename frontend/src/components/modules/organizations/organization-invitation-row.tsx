"use client";

/**
 * One row in the organization invitation list.
 *
 * Shows who was invited, the role offered, the invitation's status pill, and
 * expiry copy computed live from `expires_at`. Resend is offered on pending
 * and expired rows (the two states a fresh email can help); revoke only on
 * pending rows, since every other state is already terminal.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import type { OrgInvitationResponse } from "@/lib/generated/types.gen";
import { formatShortDate } from "@/lib/marketplace/format";

const DAY_MS = 86_400_000;

/**
 * Describe when an invitation lapses, or when it lapsed.
 *
 * Pending invitations count down in whole days (rounded up, so a link that
 * dies tomorrow morning still reads "1 day"); an expired one names the date.
 * Accepted, declined, and revoked invitations have no useful expiry, so they
 * get no copy at all.
 *
 * @param invitation - Invitation carrying `status` and `expires_at`.
 * @param now - Reference time, injectable for tests.
 */
export function describeInvitationExpiry(
  invitation: Pick<OrgInvitationResponse, "status" | "expires_at">,
  now: Date = new Date(),
): string | null {
  if (invitation.status === "expired") {
    return `Expired ${formatShortDate(invitation.expires_at)}`;
  }
  if (invitation.status !== "pending") {
    return null;
  }
  const remaining = new Date(invitation.expires_at).getTime() - now.getTime();
  if (Number.isNaN(remaining)) {
    return null;
  }
  const days = Math.max(Math.ceil(remaining / DAY_MS), 0);
  if (days === 0) return "Expires today";
  return `Expires in ${days} ${days === 1 ? "day" : "days"}`;
}

type OrganizationInvitationRowProps = {
  invitation: OrgInvitationResponse;
  /** Whether the org is suspended (blocks every mutation). */
  disabled: boolean;
  /** Whether this row's resend request is in flight. */
  resending: boolean;
  onResend: (invitation: OrgInvitationResponse) => void;
  onRevoke: (invitation: OrgInvitationResponse) => void;
};

/**
 * Render one invitation with its status, expiry, and available actions.
 *
 * @param props - Invitation, busy/disabled flags, and action callbacks.
 */
export function OrganizationInvitationRow({
  invitation,
  disabled,
  resending,
  onResend,
  onRevoke,
}: OrganizationInvitationRowProps) {
  const expiry = describeInvitationExpiry(invitation);
  const canResend = invitation.status === "pending" || invitation.status === "expired";
  const canRevoke = invitation.status === "pending";

  return (
    <li className="flex flex-col justify-between gap-4 p-6 transition-colors hover:bg-surface-2 sm:flex-row sm:items-center">
      <div className="min-w-0">
        <p className="truncate font-semibold text-foreground">{invitation.email}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusPill status={invitation.status} />
          <StatusPill status={invitation.role} />
          {expiry ? (
            <span className="text-xs text-foreground-muted">{expiry}</span>
          ) : null}
          <span className="text-xs text-foreground-muted">
            Sent {formatShortDate(invitation.created_at)}
          </span>
        </div>
      </div>

      {canResend || canRevoke ? (
        <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
          {canResend ? (
            <Button
              className="min-h-11 px-4"
              disabled={disabled}
              loading={resending}
              onClick={() => onResend(invitation)}
              variant="secondary"
            >
              Resend
            </Button>
          ) : null}
          {canRevoke ? (
            <Button
              className="min-h-11 px-4"
              disabled={disabled || resending}
              onClick={() => onRevoke(invitation)}
              variant="destructive"
            >
              Revoke
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
