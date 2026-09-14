"use client";

/**
 * Organization members tab.
 *
 * Lists everyone with access to the organization with their role and the
 * teams they sit on. Owners can switch members between admin and member;
 * owners and admins can remove anyone but the owner. The invite call-to-action sends admins to the
 * invitations tab rather than duplicating the form here.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { StatusPill } from "@/components/ui/status-pill";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import {
  changeMemberRoleV1OrgsOrgIdMembersMemberIdPatch,
  listMembersV1OrgsOrgIdMembersGet,
  removeMemberV1OrgsOrgIdMembersMemberIdDelete,
} from "@/lib/generated/sdk.gen";
import type { OrgMemberResponse } from "@/lib/generated/types.gen";
import { formatShortDate } from "@/lib/marketplace/format";
import { useOrganization } from "./organization-context";

/**
 * Render the member list with role controls and removal.
 */
export function OrganizationMembers() {
  const { orgId, role: myRole, isSuspended } = useOrganization();
  const router = useRouter();

  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [memberToRemove, setMemberToRemove] = useState<OrgMemberResponse | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  const isOwner = myRole === "owner";
  const isAdmin = myRole === "admin" || isOwner;

  async function loadMembers() {
    try {
      const result = await listMembersV1OrgsOrgIdMembersGet({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setMembers(result.data.members);
      } else {
        setError(describeGeneratedError(result.error));
      }
    } catch {
      setError("An error occurred loading members.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadMembers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  async function handleRoleChange(memberId: string, newRole: "admin" | "member") {
    if (!isOwner || isSuspended) return;
    setActionError(null);
    try {
      const result = await changeMemberRoleV1OrgsOrgIdMembersMemberIdPatch({
        path: { org_id: orgId, member_id: memberId },
        body: { role: newRole },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setActionError(describeGeneratedError(result.error));
      } else {
        await loadMembers();
      }
    } catch {
      setActionError("Unexpected error occurred while changing role.");
    }
  }

  async function handleRemoveMember() {
    if (!isAdmin || !memberToRemove || isSuspended) return;
    setIsRemoving(true);
    setActionError(null);
    try {
      const result = await removeMemberV1OrgsOrgIdMembersMemberIdDelete({
        path: { org_id: orgId, member_id: memberToRemove.id },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setActionError(describeGeneratedError(result.error));
        return;
      }
      // Removing yourself ends your access: the reload comes back 403, which
      // is the cue to leave the organization's pages.
      const reload = await listMembersV1OrgsOrgIdMembersGet({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (reload.response.status === 403) {
        router.push("/dashboard/organizations");
      } else if (reload.data) {
        setMembers(reload.data.members);
      }
    } catch {
      setActionError("Unexpected error occurred while removing member.");
    } finally {
      setIsRemoving(false);
      setMemberToRemove(null);
    }
  }

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  return (
    <div className="max-w-4xl rounded-2xl border border-border-default bg-surface-1 shadow-sm">
      <div className="flex flex-col gap-4 border-b border-border-default p-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-heading text-xl font-bold text-foreground">Organization Members</h2>
          <p className="mt-1 text-sm text-foreground-muted">
            People with access to this organization.
          </p>
        </div>
        {isAdmin ? (
          <Link
            className="inline-flex min-h-11 items-center justify-center rounded-xl border border-transparent bg-foreground px-5 text-sm font-semibold text-background transition-colors hover:bg-foreground/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            href={`/dashboard/organizations/${orgId}/invitations`}
          >
            Invite a member
          </Link>
        ) : null}
      </div>

      {actionError && (
        <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
          {actionError}
        </div>
      )}

      <ul className="divide-y divide-border-default">
        {members.length === 0 ? (
          <li className="p-6 text-center text-foreground-muted">No members found.</li>
        ) : (
          members.map((member) => (
            <li
              key={member.id}
              className="flex flex-col justify-between gap-4 p-6 transition-colors hover:bg-surface-2 sm:flex-row sm:items-center"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold text-foreground">{member.display_name}</p>
                  <StatusPill status={member.role} />
                </div>
                {member.email && (
                  <p className="mt-1 truncate text-sm text-foreground-muted">{member.email}</p>
                )}
                <p className="mt-1 text-xs text-foreground-muted">
                  Joined {formatShortDate(member.joined_at)}
                </p>
                {member.teams && member.teams.length > 0 ? (
                  <ul
                    aria-label={`Teams for ${member.display_name}`}
                    className="mt-2 flex flex-wrap gap-1.5"
                  >
                    {member.teams.map((team) => (
                      <li
                        key={team.id}
                        className="max-w-full truncate rounded-badge border border-border-default bg-surface-2 px-2 py-0.5 text-xs text-foreground-muted"
                      >
                        {team.name}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>

              {member.role !== "owner" && (isOwner || isAdmin) ? (
                <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center">
                  {isOwner ? (
                    <>
                      <label className="sr-only" htmlFor={`role-${member.id}`}>
                        Role for {member.display_name}
                      </label>
                      <Select
                        id={`role-${member.id}`}
                        className="min-h-11 w-full sm:w-32"
                        disabled={isSuspended}
                        value={member.role}
                        onChange={(e) =>
                          void handleRoleChange(member.id, e.target.value as "admin" | "member")
                        }
                      >
                        <option value="admin">Admin</option>
                        <option value="member">Member</option>
                      </Select>
                    </>
                  ) : null}
                  <Button
                    aria-label={`Remove ${member.display_name}`}
                    className="min-h-11 px-4"
                    disabled={isSuspended}
                    onClick={() => setMemberToRemove(member)}
                    variant="destructive"
                  >
                    Remove
                  </Button>
                </div>
              ) : null}
            </li>
          ))
        )}
      </ul>

      <ConfirmDialog
        open={!!memberToRemove}
        title={memberToRemove ? `Remove ${memberToRemove.display_name}?` : "Remove member"}
        description="Are you sure you want to remove this member from the organization? They will lose all access immediately."
        confirmLabel="Remove Member"
        tone="danger"
        busy={isRemoving}
        onConfirm={handleRemoveMember}
        onClose={() => setMemberToRemove(null)}
      />
    </div>
  );
}
