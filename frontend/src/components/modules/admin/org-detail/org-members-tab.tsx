"use client";

/**
 * Members tab of the admin organization detail page: each member's name,
 * email, role, teams and join date, plus the pending invitation count.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useCallback } from "react";

import { EmptyNote, ListRow, PanelError, PanelSkeleton, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { StatusPill } from "@/components/ui/status-pill";
import { adminOrgMembersV1AdminOrgsOrgIdMembersGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgMembersResponse } from "@/lib/generated/types.gen";
import { formatShortDate } from "@/lib/marketplace/format";

/**
 * Render the members tab.
 *
 * @param orgId - Organization whose members to list.
 */
export function OrgMembersTab({ orgId }: { orgId: string }) {
  const load = useCallback(
    (headers: Record<string, string>) =>
      adminOrgMembersV1AdminOrgsOrgIdMembersGet({ headers, path: { org_id: orgId } }),
    [orgId],
  );
  const { data, error, loading, retry } = useAdminOrgResource<AdminOrgMembersResponse>(load);

  if (loading) return <PanelSkeleton />;
  if (error || !data) return <PanelError message={error ?? "Could not load members."} onRetry={retry} />;

  const invitations = data.pending_invitation_count;
  return (
    <Section
      aside={`${invitations} pending ${invitations === 1 ? "invitation" : "invitations"}`}
      title={`Members (${data.members.length})`}
    >
      {data.members.length === 0 ? (
        <EmptyNote>No members.</EmptyNote>
      ) : (
        <ul className="grid gap-2">
          {data.members.map((member) => (
            <ListRow columns="md:grid-cols-[2fr_auto_2fr_auto]" key={member.member_id}>
              <div className="min-w-0">
                <p className="break-words font-semibold text-foreground">{member.display_name}</p>
                <p className="break-all text-sm text-foreground-muted">{member.email}</p>
              </div>
              <StatusPill className="w-fit" status={member.role} />
              <p className="break-words text-sm text-foreground-muted">
                {member.teams.length > 0 ? member.teams.map((team) => team.name).join(", ") : "No teams"}
              </p>
              <p className="text-sm text-foreground-muted">Joined {formatShortDate(member.joined_at)}</p>
            </ListRow>
          ))}
        </ul>
      )}
    </Section>
  );
}
