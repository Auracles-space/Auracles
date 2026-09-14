"use client";

/**
 * Invite form for the organization invitations tab.
 *
 * Masked member search for existing users (sent as `user_id`) with the manual
 * outsider-email fallback (sent as `email`), plus the role to offer. Owns its
 * own submission state; the parent only learns that an invitation was sent.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { createInvitationV1OrgsOrgIdInvitationsPost } from "@/lib/generated/sdk.gen";
import type { OrgInvitationCreateRequest } from "@/lib/generated/types.gen";
import { InviteMemberTypeahead } from "./invite-member-typeahead";

type OrganizationInviteFormProps = {
  orgId: string;
  /** Whether the org is suspended (blocks sending). */
  disabled: boolean;
  /** Called after the API accepts the invitation. */
  onInvited: () => void | Promise<void>;
};

/**
 * Render the invite form and submit it through the generated client.
 *
 * @param props - Organization id, suspended flag, and the sent callback.
 */
export function OrganizationInviteForm({ orgId, disabled, onInvited }: OrganizationInviteFormProps) {
  const [inviteEmail, setInviteEmail] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [inviteRole, setInviteRole] = useState<"admin" | "member">("member");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (disabled) return;
    if (!selectedUserId && inviteEmail.trim() === "") {
      setInviteError("Enter an email address or choose a suggested member.");
      return;
    }
    setInviteLoading(true);
    setInviteError(null);
    try {
      const body: OrgInvitationCreateRequest = selectedUserId
        ? { user_id: selectedUserId, role: inviteRole }
        : { email: inviteEmail, role: inviteRole };
      const result = await createInvitationV1OrgsOrgIdInvitationsPost({
        path: { org_id: orgId },
        body,
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setInviteError(describeGeneratedError(result.error));
        return;
      }
      setInviteEmail("");
      setSelectedUserId(null);
      setInviteRole("member");
      await onInvited();
    } catch {
      setInviteError("Unexpected error occurred while inviting.");
    } finally {
      setInviteLoading(false);
    }
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h2 className="mb-4 font-heading text-xl font-bold text-foreground">Invite Member</h2>
      {inviteError && (
        <div className="mb-4 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
          {inviteError}
        </div>
      )}
      <form onSubmit={handleInvite} className="flex flex-col items-end gap-4 sm:flex-row">
        <div className="w-full flex-grow sm:w-auto">
          <InviteMemberTypeahead
            disabled={disabled}
            orgId={orgId}
            value={inviteEmail}
            onEmailChange={(nextValue) => {
              setInviteEmail(nextValue);
              setSelectedUserId(null);
            }}
            onSelect={(userId) => {
              setSelectedUserId(userId);
              setInviteError(null);
            }}
          />
        </div>
        <div className="w-full shrink-0 sm:w-40">
          <label htmlFor="role" className="mb-1 block text-sm font-semibold text-foreground">
            Role
          </label>
          <Select
            id="role"
            disabled={disabled}
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as "admin" | "member")}
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </Select>
        </div>
        <Button type="submit" loading={inviteLoading} disabled={disabled} className="w-full sm:w-auto">
          Send Invite
        </Button>
      </form>
    </div>
  );
}
