"use client";

import { useEffect, useState } from "react";
import { 
  listMembersV1OrgsOrgIdMembersGet, 
  changeMemberRoleV1OrgsOrgIdMembersMemberIdPatch,
  removeMemberV1OrgsOrgIdMembersMemberIdDelete
} from "@/lib/generated/sdk.gen";
import type { OrgMemberResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Select } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useOrganization } from "./organization-context";
import { useRouter } from "next/navigation";

export function OrganizationMembers() {
  const { orgId, role: myRole, isSuspended } = useOrganization();
  const router = useRouter();

  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  
  // Removal Confirmation State
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
        setMembers(result.data);
      } else {
        setError("Failed to load members.");
      }
    } catch (err) {
      setError("An error occurred loading members.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMembers();
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
        setActionError(result.error?.detail?.error_code || "Failed to update role");
      } else {
        await loadMembers();
      }
    } catch (err) {
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
        setActionError(result.error?.detail?.error_code || "Failed to remove member");
        setIsRemoving(false);
        setMemberToRemove(null);
      } else {
        setMemberToRemove(null);
        setIsRemoving(false);
        // Self-removal = leaving the org
        // Currently we don't have user_id of the current viewer natively in this context,
        // but if the user removes themselves, they will get a 403 on reload or we can assume
        // that if it succeeded and it was them, we'd better navigate them away.
        // For simplicity, if we redirect to /dashboard/organizations on any removal, that might be jarring.
        // Let's just reload. If they removed themselves, the loadMembers will 403 or return empty.
        // Wait, we can check if the member removed has the same role. But best is to rely on reload.
        const res = await listMembersV1OrgsOrgIdMembersGet({
          path: { org_id: orgId },
          headers: getAccessTokenHeaders(),
        });
        if (res.response.status === 403) {
          router.push("/dashboard/organizations");
        } else if (res.data) {
          setMembers(res.data);
        }
      }
    } catch (err) {
      setActionError("Unexpected error occurred while removing member.");
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
    return <p className="text-error">{error}</p>;
  }

  return (
    <div className="max-w-4xl rounded-2xl border border-border-default bg-surface-1 shadow-sm">
      <div className="border-b border-border-default p-6">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Organization Members
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          People with access to this organization.
        </p>
      </div>

      {actionError && (
        <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
          {actionError}
        </div>
      )}

      <ul className="divide-y divide-border-default">
        {members.map((member) => (
          <li key={member.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 hover:bg-surface-2 transition-colors">
            <div>
              <p className="font-semibold text-foreground">{member.display_name}</p>
              {member.email && <p className="text-sm text-foreground-muted">{member.email}</p>}
              <p className="mt-1 text-xs text-foreground-muted">
                Joined {new Date(member.joined_at).toLocaleDateString()}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {/* Role Display / Switcher */}
              {isOwner && member.role !== "owner" ? (
                <Select
                  disabled={isSuspended}
                  value={member.role}
                  onChange={(e) => handleRoleChange(member.id, e.target.value as "admin" | "member")}
                  className="w-32 min-h-10 py-1"
                >
                  <option value="admin">Admin</option>
                  <option value="member">Member</option>
                </Select>
              ) : (
                <span className="rounded-badge bg-surface-2 px-3 py-1 text-xs font-medium uppercase tracking-wider text-foreground-muted">
                  {member.role}
                </span>
              )}

              {/* Remove Action */}
              {isAdmin && member.role !== "owner" && (
                <Button
                  variant="destructive"
                  className="min-h-10 px-4 py-1"
                  disabled={isSuspended}
                  onClick={() => setMemberToRemove(member)}
                >
                  Remove
                </Button>
              )}
            </div>
          </li>
        ))}
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
