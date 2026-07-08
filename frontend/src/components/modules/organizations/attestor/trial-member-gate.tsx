"use client";

import { useState } from "react";
import { nominateOrgAttestorTrialMember } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

  const isNominated = !!application?.trial_member_id;

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
          <label htmlFor="trial_member_id" className="mb-1 block text-sm font-semibold text-foreground">
            Nominee Member ID
          </label>
          <Input
            id="trial_member_id"
            type="text"
            value={memberId}
            onChange={(e) => setMemberId(e.target.value)}
            placeholder="member-123"
            required
          />
          <p className="mt-1 text-xs text-foreground-muted">
            This person will complete the trial attestation on behalf of your organization.
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
