"use client";

import { useState } from "react";
import { signOrgAttestorUndertakings } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useOrganization } from "@/components/modules/organizations/organization-context";

export function UndertakingsGate({
  application,
  onChange,
}: {
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const { role, orgId } = useOrganization();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [acceptPolicy, setAcceptPolicy] = useState(false);
  const [acceptConfidentiality, setAcceptConfidentiality] = useState(false);
  const [totpCode, setTotpCode] = useState("");

  const isSigned = !!application?.confidentiality_signed_at;

  if (isSigned) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm text-sm text-foreground">
        Undertakings have been signed by the organization owner.
      </div>
    );
  }

  if (role !== "owner") {
    return (
      <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm text-sm text-foreground-muted">
        Only the organization owner can sign the confidentiality undertaking.
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!acceptPolicy || !acceptConfidentiality) {
      setError("You must accept both declarations.");
      return;
    }
    if (!totpCode || totpCode.length !== 6) {
      setError("Please enter a valid 6-digit authenticator code.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await signOrgAttestorUndertakings({
        path: { org_id: orgId },
        body: {
          declarations: [],
          accept_policy: acceptPolicy,
          accept_confidentiality: acceptConfidentiality,
          totp_code: totpCode,
        },
        headers: getAccessTokenHeaders(),
      });

      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch (e) {
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
        <label htmlFor="accept_policy" className="flex items-start gap-3 text-sm">
          <input
            id="accept_policy"
            type="checkbox"
            checked={acceptPolicy}
            onChange={(e) => setAcceptPolicy(e.target.checked)}
            className="mt-1 size-4 shrink-0 rounded border-border-default bg-background text-foreground focus:ring-accent"
          />
          <span className="text-foreground">
            I accept the organization attestor policy and terms of service.
          </span>
        </label>

        <label htmlFor="accept_confidentiality" className="flex items-start gap-3 text-sm">
          <input
            id="accept_confidentiality"
            type="checkbox"
            checked={acceptConfidentiality}
            onChange={(e) => setAcceptConfidentiality(e.target.checked)}
            className="mt-1 size-4 shrink-0 rounded border-border-default bg-background text-foreground focus:ring-accent"
          />
          <span className="text-foreground">
            I accept the confidentiality undertaking and agree to protect sensitive information.
          </span>
        </label>

        <div className="pt-2">
          <label htmlFor="totp_code" className="mb-1 block text-sm font-semibold text-foreground">
            Authenticator Code
          </label>
          <Input
            id="totp_code"
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value)}
            placeholder="123456"
            maxLength={6}
            className="max-w-[200px]"
          />
          <p className="mt-1 text-xs text-foreground-muted">
            Provide your 2FA code to cryptographically sign this undertaking.
          </p>
        </div>

        <div className="pt-2">
          <Button type="submit" disabled={loading || !acceptPolicy || !acceptConfidentiality || !totpCode} loading={loading}>
            Sign Undertakings
          </Button>
        </div>
      </form>
    </div>
  );
}
