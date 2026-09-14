"use client";

/**
 * Team member roster manager.
 *
 * Expanded panel rendered under a team row. Lists the team's current members
 * and lets admins add organization members not yet on the team or remove
 * members already on it. The org-member list minus the current roster forms
 * the "add member" options, so a member is never offered twice.
 *
 * Maps to: FR-ORG-018.
 */
import { useEffect, useState } from "react";

import {
  addTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdPut,
  listMembersV1OrgsOrgIdMembersGet,
  listTeamMembersV1OrgsOrgIdTeamsTeamIdMembersGet,
  removeTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdDelete,
} from "@/lib/generated/sdk.gen";
import type { OrgMemberResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Cross2Icon } from "@radix-ui/react-icons";

type TeamMemberManagerProps = {
  /** Organization id owning the team. */
  orgId: string;
  /** Team whose roster is being managed. */
  teamId: string;
  /** Whether the caller may mutate the roster. */
  isAdmin: boolean;
  /** Whether the org is suspended (blocks mutations). */
  isSuspended: boolean;
  /** Called after a successful add/remove so the parent can refresh counts. */
  onChange?: () => void;
};

/**
 * Render the add/remove roster panel for one team.
 *
 * @param props - Org/team ids, permission flags, and a change callback.
 */
export function TeamMemberManager({
  orgId,
  teamId,
  isAdmin,
  isSuspended,
  onChange,
}: TeamMemberManagerProps) {
  const [roster, setRoster] = useState<OrgMemberResponse[]>([]);
  const [orgMembers, setOrgMembers] = useState<OrgMemberResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [rosterRes, membersRes] = await Promise.all([
        listTeamMembersV1OrgsOrgIdTeamsTeamIdMembersGet({
          path: { org_id: orgId, team_id: teamId },
          headers: getAccessTokenHeaders(),
        }),
        listMembersV1OrgsOrgIdMembersGet({
          path: { org_id: orgId },
          headers: getAccessTokenHeaders(),
        }),
      ]);
      if (rosterRes.response.ok && rosterRes.data) {
        setRoster(rosterRes.data.members);
      } else {
        setError(describeGeneratedError(rosterRes.error));
      }
      if (membersRes.response.ok && membersRes.data) {
        setOrgMembers(membersRes.data.members);
      }
    } catch {
      setError("An error occurred loading team members.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, teamId]);

  const rosterIds = new Set(roster.map((member) => member.id));
  const candidates = orgMembers.filter((member) => !rosterIds.has(member.id));

  async function handleAdd() {
    if (!selectedId || isSuspended) return;
    setAdding(true);
    setError(null);
    try {
      const res = await addTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdPut({
        path: { org_id: orgId, team_id: teamId, member_id: selectedId },
        headers: getAccessTokenHeaders(),
      });
      if (res.response.ok) {
        setSelectedId("");
        await load();
        onChange?.();
      } else {
        setError(describeGeneratedError(res.error));
      }
    } catch {
      setError("Unexpected error occurred while adding member.");
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(memberId: string) {
    if (isSuspended) return;
    setBusyId(memberId);
    setError(null);
    try {
      const res =
        await removeTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdDelete({
          path: { org_id: orgId, team_id: teamId, member_id: memberId },
          headers: getAccessTokenHeaders(),
        });
      if (res.response.ok) {
        setRoster((prev) => prev.filter((member) => member.id !== memberId));
        onChange?.();
      } else {
        setError(describeGeneratedError(res.error));
      }
    } catch {
      setError("Unexpected error occurred while removing member.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex h-20 items-center justify-center border-t border-border-default bg-surface-2/30">
        <Spinner className="h-5 w-5 text-accent" />
      </div>
    );
  }

  return (
    <div className="border-t border-border-default bg-surface-2/30 px-6 py-5 sm:px-8">
      {error && (
        <div className="mb-4 rounded-xl border border-error/40 bg-error/5 px-4 py-3 text-sm text-error">
          {error}
        </div>
      )}

      {roster.length === 0 ? (
        <p className="text-sm text-foreground-muted">No members on this team yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {roster.map((member) => (
            <li
              key={member.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-1 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground">
                  {member.display_name}
                </p>
                {member.email && (
                  <p className="truncate text-xs text-foreground-muted">
                    {member.email}
                  </p>
                )}
              </div>
              {isAdmin && (
                <button
                  type="button"
                  disabled={isSuspended || busyId === member.id}
                  title={`Remove ${member.display_name} from team`}
                  aria-label={`Remove ${member.display_name} from team`}
                  onClick={() => handleRemove(member.id)}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-error/30 bg-error/5 text-error transition-colors hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busyId === member.id ? (
                    <Spinner className="h-4 w-4" />
                  ) : (
                    <Cross2Icon className="h-4 w-4" />
                  )}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {isAdmin && (
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <label htmlFor={`add-member-${teamId}`} className="sr-only">
            Add member to team
          </label>
          <select
            id={`add-member-${teamId}`}
            disabled={isSuspended || candidates.length === 0}
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
            className="min-h-11 flex-1 rounded-xl border border-border-default bg-background px-3 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">
              {candidates.length === 0
                ? "All members are on this team"
                : "Select a member to add…"}
            </option>
            {candidates.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_name}
              </option>
            ))}
          </select>
          <Button
            type="button"
            loading={adding}
            disabled={isSuspended || !selectedId}
            onClick={handleAdd}
            className="w-full shrink-0 sm:w-auto"
          >
            Add member
          </Button>
        </div>
      )}
    </div>
  );
}
