"use client";

/**
 * Organization invitation management panel for org admins.
 *
 * Composes the invite form with the invitation history, filtered by status.
 * Pending and expired invitations can be resent; pending ones can be revoked.
 * Server refusals are shown with their own message.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { SegmentedControl, type SegmentOption } from "@/components/ui/segmented-control";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import {
  listInvitationsV1OrgsOrgIdInvitationsGet,
  resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost,
  revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete,
} from "@/lib/generated/sdk.gen";
import type { OrgInvitationResponse } from "@/lib/generated/types.gen";
import { useOrganization } from "./organization-context";
import { OrganizationInvitationRow } from "./organization-invitation-row";
import { OrganizationInviteForm } from "./organization-invite-form";

type InvitationFilter = "pending" | "accepted" | "declined" | "revoked" | "expired" | "all";

const FILTER_OPTIONS: SegmentOption<InvitationFilter>[] = [
  { value: "pending", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "declined", label: "Declined" },
  { value: "revoked", label: "Revoked" },
  { value: "expired", label: "Expired" },
  { value: "all", label: "All" },
];

const EMPTY_COPY: Record<InvitationFilter, string> = {
  pending: "No pending invitations.",
  accepted: "No accepted invitations yet.",
  declined: "No declined invitations.",
  revoked: "No revoked invitations.",
  expired: "No expired invitations.",
  all: "No invitations have been sent yet.",
};

/**
 * Render the organization invite form and filtered invitation history.
 */
export function OrganizationInvitations() {
  const { orgId, role, isSuspended } = useOrganization();
  const isAdmin = role === "admin" || role === "owner";
  const toast = useToast();

  const [invitations, setInvitations] = useState<OrgInvitationResponse[]>([]);
  const [filter, setFilter] = useState<InvitationFilter>("pending");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [invitationToRevoke, setInvitationToRevoke] = useState<OrgInvitationResponse | null>(null);
  const [revokeLoading, setRevokeLoading] = useState(false);
  const [resendingId, setResendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadInvitations = useCallback(async () => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    try {
      const result = await listInvitationsV1OrgsOrgIdInvitationsGet({
        path: { org_id: orgId },
        query: { status: filter },
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setInvitations(result.data.invitations);
        setError(null);
      } else {
        setError(describeGeneratedError(result.error));
      }
    } catch {
      setError("An error occurred loading invitations.");
    } finally {
      setLoading(false);
    }
  }, [orgId, isAdmin, filter]);

  useEffect(() => {
    void loadInvitations();
  }, [loadInvitations]);

  /** A fresh invitation is pending, so jump the history to where it lands. */
  async function handleInvited() {
    if (filter === "pending" || filter === "all") {
      await loadInvitations();
    } else {
      setFilter("pending");
    }
  }

  async function handleResend(invitation: OrgInvitationResponse) {
    if (!isAdmin || isSuspended) return;
    setResendingId(invitation.id);
    setActionError(null);
    try {
      const result = await resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost({
        path: { org_id: orgId, invitation_id: invitation.id },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setActionError(describeGeneratedError(result.error));
        return;
      }
      toast.success(`Invitation resent to ${invitation.email}.`);
      await loadInvitations();
    } catch {
      setActionError("Unexpected error occurred while resending.");
    } finally {
      setResendingId(null);
    }
  }

  async function handleRevoke() {
    if (!isAdmin || !invitationToRevoke || isSuspended) return;
    setRevokeLoading(true);
    setActionError(null);
    try {
      const result = await revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete({
        path: { org_id: orgId, invitation_id: invitationToRevoke.id },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setActionError(describeGeneratedError(result.error));
      } else {
        await loadInvitations();
      }
    } catch {
      setActionError("Unexpected error occurred while revoking.");
    } finally {
      setRevokeLoading(false);
      setInvitationToRevoke(null);
    }
  }

  if (!isAdmin) {
    return (
      <div className="rounded-2xl border border-error/50 bg-error/5 p-6 text-center text-error">
        You do not have permission to view this page.
      </div>
    );
  }

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <OrganizationInviteForm disabled={isSuspended} onInvited={handleInvited} orgId={orgId} />

      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm">
        <div className="border-b border-border-default p-6">
          <h2 className="font-heading text-xl font-bold text-foreground">Invitations</h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Everyone invited to this organization, by outcome. Pending links expire after a
            while; resend one to issue a fresh link.
          </p>
          <SegmentedControl
            className="mt-4"
            label="Filter invitations by status"
            onChange={setFilter}
            options={FILTER_OPTIONS}
            value={filter}
          />
        </div>

        {(error || actionError) && (
          <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {error || actionError}
          </div>
        )}

        {loading ? (
          <div className="flex h-32 items-center justify-center">
            <Spinner className="h-6 w-6 text-accent" />
          </div>
        ) : (
          <ul className="divide-y divide-border-default">
            {invitations.length === 0 ? (
              <li className="p-6 text-center text-foreground-muted">{EMPTY_COPY[filter]}</li>
            ) : (
              invitations.map((invitation) => (
                <OrganizationInvitationRow
                  disabled={isSuspended}
                  invitation={invitation}
                  key={invitation.id}
                  onResend={(target) => void handleResend(target)}
                  onRevoke={setInvitationToRevoke}
                  resending={resendingId === invitation.id}
                />
              ))
            )}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={!!invitationToRevoke}
        title="Revoke invitation?"
        description={`Are you sure you want to revoke the invitation for ${invitationToRevoke?.email}? They will no longer be able to join the organization.`}
        confirmLabel="Revoke Invitation"
        tone="danger"
        busy={revokeLoading}
        onConfirm={handleRevoke}
        onClose={() => setInvitationToRevoke(null)}
      />
    </div>
  );
}
