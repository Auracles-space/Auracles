"use client";

import { useEffect, useState } from "react";
import { listMembersV1OrgsOrgIdMembersGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgMemberResponse } from "@/lib/generated/types.gen";
import { Spinner } from "@/components/ui/spinner";

export type ReviewingMemberPickerProps = {
  orgId: string;
  value: string;
  onChange: (memberId: string) => void;
};

export function ReviewingMemberPicker({ orgId, value, onChange }: ReviewingMemberPickerProps) {
  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      setLoading(true);
      setError(null);
      const res = await listMembersV1OrgsOrgIdMembersGet({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) return;
      setLoading(false);
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else if (res.data) {
        setMembers(res.data.members);
      }
    }
    load();
    return () => { mounted = false; };
  }, [orgId]);

  if (loading) {
    return <div className="p-4 flex items-center justify-center gap-2 text-sm text-foreground-muted"><Spinner className="w-4 h-4" /> Loading members...</div>;
  }

  if (error) {
    return <div className="p-3 text-sm text-error bg-error/5 border border-error/20 rounded-md">{error}</div>;
  }

  if (members.length === 0) {
    return <div className="p-4 text-sm text-foreground-muted text-center italic">No members available.</div>;
  }

  return (
    <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
      {members.map((member) => (
        <label
          key={member.id}
          className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
            value === member.id 
              ? "border-primary bg-primary/5" 
              : "border-border-default hover:bg-surface-2"
          }`}
        >
          <input
            type="radio"
            name="reviewing_member_id"
            value={member.id}
            checked={value === member.id}
            onChange={() => onChange(member.id)}
            className="w-4 h-4 text-primary bg-background border-border-default focus:ring-primary/20"
          />
          <div className="flex flex-col">
            <span className="text-sm font-medium text-foreground">{member.display_name}</span>
            <span className="text-xs text-foreground-muted capitalize">{member.role}</span>
          </div>
        </label>
      ))}
    </div>
  );
}
