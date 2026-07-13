"use client";

import { useEffect, useState } from "react";
import { 
  listInvitationsV1OrgsOrgIdInvitationsGet, 
  createInvitationV1OrgsOrgIdInvitationsPost,
  revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete
} from "@/lib/generated/sdk.gen";
import type { OrgInvitationResponse, OrgInvitationCreateRequest } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useOrganization } from "./organization-context";
import { Badge } from "@/components/ui/badge";

export function OrganizationInvitations() {
  const { orgId, role, isSuspended } = useOrganization();
  const isAdmin = role === "admin" || role === "owner";

  const [invitations, setInvitations] = useState<OrgInvitationResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Invite Form State
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member">("member");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  // Revoke State
  const [invitationToRevoke, setInvitationToRevoke] = useState<OrgInvitationResponse | null>(null);
  const [revokeLoading, setRevokeLoading] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  async function loadInvitations() {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    
    try {
      const result = await listInvitationsV1OrgsOrgIdInvitationsGet({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setInvitations(result.data.invitations);
      } else {
        setError("Failed to load invitations.");
      }
    } catch {
      setError("An error occurred loading invitations.");
    } finally {
      setLoading(false);
    }
  }

    useEffect(() => {
    loadInvitations();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, isAdmin]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!isAdmin || isSuspended) return;

    setInviteLoading(true);
    setInviteError(null);

    try {
      const body: OrgInvitationCreateRequest = { email: inviteEmail, role: inviteRole };
      const result = await createInvitationV1OrgsOrgIdInvitationsPost({
        path: { org_id: orgId },
        body,
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setInviteError(result.error?.detail?.error_code || "Failed to invite user");
      } else {
        setInviteEmail("");
        setInviteRole("member");
        await loadInvitations();
      }
    } catch {
      setInviteError("Unexpected error occurred while inviting.");
    } finally {
      setInviteLoading(false);
    }
  }

  async function handleRevoke() {
    if (!isAdmin || !invitationToRevoke || isSuspended) return;

    setRevokeLoading(true);
    setRevokeError(null);

    try {
      const result = await revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete({
        path: { org_id: orgId, invitation_id: invitationToRevoke.id },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setRevokeError(result.error?.detail?.error_code || "Failed to revoke invitation");
        setRevokeLoading(false);
        setInvitationToRevoke(null);
      } else {
        setInvitationToRevoke(null);
        setRevokeLoading(false);
        await loadInvitations();
      }
    } catch {
      setRevokeError("Unexpected error occurred while revoking.");
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

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8 max-w-4xl">
      {/* Invite Form */}
      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm p-6">
        <h2 className="mb-4 font-heading text-xl font-bold text-foreground">
          Invite Member
        </h2>
        {inviteError && (
          <div className="mb-4 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {inviteError}
          </div>
        )}
        <form onSubmit={handleInvite} className="flex flex-col sm:flex-row gap-4 items-end">
          <div className="flex-grow w-full sm:w-auto">
            <label htmlFor="email" className="mb-1 block text-sm font-semibold text-foreground">
              Email Address
            </label>
            <Input
              id="email"
              type="email"
              required
              disabled={isSuspended}
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="colleague@example.com"
            />
          </div>
          <div className="w-full sm:w-40 shrink-0">
            <label htmlFor="role" className="mb-1 block text-sm font-semibold text-foreground">
              Role
            </label>
            <Select
              id="role"
              disabled={isSuspended}
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as "admin" | "member")}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </Select>
          </div>
          <Button type="submit" loading={inviteLoading} disabled={isSuspended} className="w-full sm:w-auto mt-4 sm:mt-0">
            Send Invite
          </Button>
        </form>
      </div>

      {/* Invitations List */}
      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm">
        <div className="border-b border-border-default p-6">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Pending Invitations
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Invitations that have not yet been accepted.
          </p>
        </div>

        {error && (
          <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {error}
          </div>
        )}
        {revokeError && (
          <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {revokeError}
          </div>
        )}

        <ul className="divide-y divide-border-default">
          {(!invitations || invitations.length === 0) ? (
            <li className="p-6 text-center text-foreground-muted">No pending invitations.</li>
          ) : (
            invitations.map((invitation) => (
              <li key={invitation.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 hover:bg-surface-2 transition-colors">
                <div>
                  <p className="font-semibold text-foreground">{invitation.email}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs uppercase tracking-wider text-foreground-muted font-medium">
                      {invitation.role}
                    </span>
                    <span className="text-foreground-muted text-xs">•</span>
                    <span className="text-xs text-foreground-muted">
                      Expires {new Date(invitation.expires_at).toLocaleDateString()}
                    </span>
                    {invitation.status && (
                      <>
                        <span className="text-foreground-muted text-xs">•</span>
                        <Badge variant={invitation.status === "pending" ? "info" : "default"}>
                          {invitation.status}
                        </Badge>
                      </>
                    )}
                  </div>
                </div>

                <Button
                  variant="secondary"
                  className="min-h-10 px-4 py-1"
                  disabled={isSuspended}
                  onClick={() => setInvitationToRevoke(invitation)}
                >
                  Revoke
                </Button>
              </li>
            ))
          )}
        </ul>
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
