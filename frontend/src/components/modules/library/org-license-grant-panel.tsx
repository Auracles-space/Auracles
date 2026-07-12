"use client";

/**
 * Organization License Grant Panel.
 *
 * Allows an organization operator to view and manage license grants
 * to specific users or teams within the organization.
 */
import { useEffect, useState } from "react";
import {
  addOrgLicenseGrant,
  listOrgLicenseGrants,
  revokeOrgLicenseGrant,
  listOrgMembers,
  listOrgTeams,
} from "@/lib/generated/sdk.gen";
import type { OrgLicenseGrantRequest, OrgLicenseGrantResponse, OrgMemberResponse, OrgTeamResponse } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Spinner } from "@/components/ui/spinner";
import { TrashIcon } from "@radix-ui/react-icons";

type OrgLicenseGrantPanelProps = {
  orgId: string;
  licenseId: string;
};

export function OrgLicenseGrantPanel({ orgId, licenseId }: OrgLicenseGrantPanelProps) {
  const [grants, setGrants] = useState<OrgLicenseGrantResponse[]>([]);
  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [teams, setTeams] = useState<OrgTeamResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [grantType, setGrantType] = useState<"member_id" | "team_id">("member_id");
  const [grantTargetId, setGrantTargetId] = useState("");

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, licenseId]);

  useEffect(() => {
    // Reset target ID when type changes so we don't accidentally submit a team ID as a user ID
    setGrantTargetId("");
  }, [grantType]);

  async function loadData() {
    setError(null);
    setLoading(true);
    configureBrowserClient();

    try {
      const [grantsRes, membersRes, teamsRes] = await Promise.all([
        listOrgLicenseGrants({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId, license_id: licenseId },
        }),
        listOrgMembers({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
        }),
        listOrgTeams({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
        }),
      ]);

      if (
        !grantsRes.response.ok || !grantsRes.data || 
        !membersRes.response.ok || !membersRes.data || 
        !teamsRes.response.ok || !teamsRes.data
      ) {
        setError(describeGeneratedError(grantsRes.error || membersRes.error || teamsRes.error));
        setLoading(false);
        return;
      }
      
      setGrants(grantsRes.data);
      setMembers(membersRes.data.members);
      setTeams(teamsRes.data.teams);
    } catch (e: unknown) {
      setError((e as Error).message);
    }
    setLoading(false);
  }

  async function reloadGrants() {
    configureBrowserClient();
    const result = await listOrgLicenseGrants({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId },
    });
    if (result.response.ok && result.data) {
      setGrants(result.data);
    }
  }

  async function handleAddGrant(e: React.FormEvent) {
    e.preventDefault();
    if (!grantTargetId.trim()) return;

    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    
    const body: OrgLicenseGrantRequest = {};
    if (grantType === "member_id") {
      body.member_id = grantTargetId.trim();
    } else {
      body.team_id = grantTargetId.trim();
    }

    const result = await addOrgLicenseGrant({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId },
      body,
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setGrantTargetId("");
    await reloadGrants();
  }

  async function handleRevokeGrant(grantId: string) {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();

    const result = await revokeOrgLicenseGrant({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId, grant_id: grantId },
    });
    setSubmitting(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    await reloadGrants();
  }

  if (loading) {
    return (
      <div className="mt-6 flex items-center gap-2 text-sm text-foreground-muted">
        <Spinner className="h-4 w-4" />
        <span>Loading grants...</span>
      </div>
    );
  }

  return (
    <div className="mt-6 rounded-xl border border-border-default bg-surface-1 p-4 shadow-sm">
      <h3 className="font-heading text-sm font-bold text-foreground">License Grants</h3>
      
      {error && <p className="mt-2 text-sm text-error">{error}</p>}
      
      <div className="mt-4">
        {grants.length === 0 ? (
          <p className="text-sm text-foreground-muted">No active grants for this license.</p>
        ) : (
          <ul className="grid gap-2">
            {grants.map((grant) => (
              <li
                key={grant.id}
                className="flex items-center justify-between rounded-lg border border-border-default bg-background px-3 py-2 text-sm"
              >
                <div>
                  <span className="font-semibold text-foreground">
                    {grant.member_id ? "User" : "Team"}
                  </span>
                  <span className="ml-2 text-foreground-muted">
                    {grant.member_id 
                      ? (members.find((m) => m.id === grant.member_id)?.display_name || grant.member_id)
                      : (teams.find((t) => t.id === grant.team_id)?.name || grant.team_id)
                    }
                  </span>
                </div>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => handleRevokeGrant(grant.id)}
                  className="text-foreground-muted transition-colors hover:text-error disabled:opacity-50"
                  aria-label="Revoke grant"
                >
                  <TrashIcon className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form onSubmit={handleAddGrant} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs font-semibold text-foreground-muted">Grant to</span>
          <div className="flex rounded-xl shadow-sm">
            <select
              value={grantType}
              onChange={(e) => setGrantType(e.target.value as "member_id" | "team_id")}
              className="rounded-l-xl border border-r-0 border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            >
              <option value="member_id">User</option>
              <option value="team_id">Team</option>
            </select>
            <select
              value={grantTargetId}
              onChange={(e) => setGrantTargetId(e.target.value)}
              className="w-full rounded-r-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent"
              disabled={submitting}
              required
            >
              <option value="" disabled>
                Select {grantType === "member_id" ? "a user" : "a team"}...
              </option>
              {grantType === "member_id"
                ? members.map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.display_name} ({member.email})
                    </option>
                  ))
                : teams.map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
            </select>
          </div>
        </label>
        <button
          type="submit"
          disabled={submitting || !grantTargetId.trim()}
          className="rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm transition-colors hover:bg-foreground/90 disabled:opacity-50 sm:mb-[1px]"
        >
          Add Grant
        </button>
      </form>
    </div>
  );
}
