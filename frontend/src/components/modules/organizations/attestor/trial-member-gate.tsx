"use client";

import { useEffect, useState } from "react";
import {
  listMembersV1OrgsOrgIdMembersGet as listMembers,
  nominateOrgAttestorTrialMember,
} from "@/lib/generated/sdk.gen";
import type {
  OrgAttestorApplicationResponse,
  OrgMemberResponse,
} from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { useOrganization } from "@/components/modules/organizations/organization-context";

export function TrialMemberGate({
  application,
  onChange,
}: {
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const { orgId } = useOrganization();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memberId, setMemberId] = useState("");
  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [membersLoading, setMembersLoading] = useState(true);

  const isNominated = !!application?.trial_member_id;

  // Load the org roster so the owner nominates by name, not by copying a
  // member's internal id. Skipped once a trial member is already stamped.
  useEffect(() => {
    if (isNominated) {
      setMembersLoading(false);
      return;
    }
    let mounted = true;
    async function load() {
      const res = await listMembers({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) return;
      setMembersLoading(false);
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else if (res.data) {
        setMembers(res.data.members);
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, [orgId, isNominated]);

  if (isNominated) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm text-sm text-foreground">
        Trial member nominated: <span className="font-semibold">{application.trial_member_id}</span>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!memberId) {
      setError("Please enter a valid member ID.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await nominateOrgAttestorTrialMember({
        path: { org_id: orgId },
        body: { member_id: memberId },
        headers: getAccessTokenHeaders(),
      });

      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="trial_member_id"
            className="mb-1 block text-sm font-semibold text-foreground"
          >
            Nominee
          </label>
          <div className="relative">
            <select
              id="trial_member_id"
              value={memberId}
              disabled={membersLoading || members.length === 0}
              onChange={(e) => setMemberId(e.target.value)}
              className="min-h-12 w-full cursor-pointer appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="" disabled hidden>
                {membersLoading
                  ? "Loading members…"
                  : members.length === 0
                    ? "No members available"
                    : "Select a member"}
              </option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.display_name}
                  {member.email ? ` (${member.email})` : ""} — {member.role}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-foreground-muted">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>
          <p className="mt-1 text-xs text-foreground-muted">
            This person will complete the trial attestation on behalf of your organization.
            They&apos;ll be notified by email and in the app.
          </p>
        </div>

        <div className="pt-2">
          <Button type="submit" disabled={loading || !memberId} loading={loading}>
            Nominate Trial Member
          </Button>
        </div>
      </form>
    </div>
  );
}
