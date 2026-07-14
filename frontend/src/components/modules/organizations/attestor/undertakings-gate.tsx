"use client";

import { useState } from "react";
import { signOrgAttestorUndertakings } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useOrganization } from "@/components/modules/organizations/organization-context";

/**
 * Scrollable panel presenting the Attestor undertakings for review.
 *
 * TODO(william, 2026-07-14): Placeholder legal text pending counsel review.
 * Replace with the finalized Attestor Policy and Confidentiality Undertaking
 * (ideally sourced from a versioned document store) before public launch.
 */
function UndertakingsDocument() {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">Undertakings</span>
        <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs font-semibold text-warning">
          Draft — pending legal review
        </span>
      </div>
      <div className="max-h-64 space-y-4 overflow-y-auto rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
        <section>
          <h4 className="mb-1 font-semibold text-foreground">
            1. Attestor Policy &amp; Terms of Service
          </h4>
          <p>
            By acting as an Organization Attestor on Auracles, your organization agrees to
            perform verifications honestly, competently, and independently. You will only
            attest to matters within your professional competence and the sectors, functions,
            and jurisdictions declared in your application.
          </p>
          <p className="mt-2">
            You agree not to attest any Framework, credential, or party where a conflict of
            interest exists, and to disclose any such conflict promptly. Auracles may suspend or
            revoke your attestor status for inaccurate, negligent, or bad-faith attestations.
          </p>
          <p className="mt-2">
            Attestations you issue are your organization&apos;s professional representations.
            You remain responsible for their accuracy and for complying with applicable laws and
            professional standards in every jurisdiction you operate in.
          </p>
        </section>

        <section>
          <h4 className="mb-1 font-semibold text-foreground">2. Confidentiality Undertaking</h4>
          <p>
            In the course of attestation work you may access non-public information belonging to
            contributors, operators, and Auracles. You agree to keep all such information strictly
            confidential, to use it solely for the purpose of performing the attestation, and not
            to disclose it to any third party without authorization.
          </p>
          <p className="mt-2">
            You will apply reasonable safeguards to protect confidential information, restrict
            access to personnel who need it, and return or destroy it on request or when it is no
            longer required. This obligation survives the termination of your attestor status.
          </p>
        </section>

        <p className="text-xs italic text-foreground-muted">
          This is placeholder text for testing and will be replaced by the final,
          legally-reviewed undertakings before launch.
        </p>
      </div>
    </div>
  );
}

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
        <UndertakingsDocument />

        <label htmlFor="accept_policy" className="flex cursor-pointer items-start gap-3 text-sm">
          <input
            id="accept_policy"
            type="checkbox"
            checked={acceptPolicy}
            onChange={(e) => setAcceptPolicy(e.target.checked)}
            className="mt-1 size-4 shrink-0 cursor-pointer rounded border-border-default bg-background text-foreground focus:ring-accent"
          />
          <span className="text-foreground">
            I have read and accept the Attestor Policy &amp; Terms of Service above.
          </span>
        </label>

        <label
          htmlFor="accept_confidentiality"
          className="flex cursor-pointer items-start gap-3 text-sm"
        >
          <input
            id="accept_confidentiality"
            type="checkbox"
            checked={acceptConfidentiality}
            onChange={(e) => setAcceptConfidentiality(e.target.checked)}
            className="mt-1 size-4 shrink-0 cursor-pointer rounded border-border-default bg-background text-foreground focus:ring-accent"
          />
          <span className="text-foreground">
            I have read and accept the Confidentiality Undertaking above and agree to protect
            sensitive information.
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
