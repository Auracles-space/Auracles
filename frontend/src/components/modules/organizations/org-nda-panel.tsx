"use client";

/**
 * Organization NDA panel.
 *
 * Shows whether the caller has signed the current NDA version, the document
 * text, and a sign action. Signing emits `NDA_SIGNED_EVENT` so the shell can
 * clear its NDA dot without a refresh.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import { useState, useEffect } from "react";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { getOrgNda, signOrgNda } from "@/lib/generated/sdk.gen";
import { emitNdaSigned } from "@/lib/organizations/org-events";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgNdaStatusResponse } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";

/**
 * Render the NDA status card for the current organization member.
 *
 * @param props - Optional callback fired after a successful signature.
 */
export function OrgNdaPanel({ onSigned }: { onSigned?: () => void }) {
  const { orgId } = useOrganization();
  const [nda, setNda] = useState<OrgNdaStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    if (!orgId) return;

    async function load() {
      setLoading(true);
      setError(null);
      const res = await getOrgNda({
        path: { org_id: orgId! },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) return;
      setLoading(false);
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else if (res.data) {
        setNda(res.data);
      }
    }
    load();
    return () => { mounted = false; };
  }, [orgId]);

  const handleSign = async () => {
    if (!orgId) return;
    setSigning(true);
    setError(null);
    const res = await signOrgNda({
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    setSigning(false);
    if (res.error) {
      setError(describeGeneratedError(res.error));
    } else if (res.data) {
      setNda(res.data);
      onSigned?.();
      // Tell the org shell to clear its NDA dot without a manual refresh.
      emitNdaSigned();
    }
  };

  if (loading) {
    return <p className="p-4 text-sm text-foreground-muted">Loading NDA status...</p>;
  }

  if (error) {
    return (
      <p className="rounded-2xl border border-error/50 bg-error/5 p-4 text-sm text-error" role="alert">
        {error}
      </p>
    );
  }

  if (!nda || !nda.required) {
    return (
      <p className="p-4 text-sm text-foreground-muted">
        No NDA is required for this organization at this time.
      </p>
    );
  }

  const isSigned = nda.signed_version === nda.current_version;

  return (
    <section className="w-full max-w-2xl overflow-hidden rounded-2xl border border-border-default bg-surface-1 shadow-sm">
      <div className="border-b border-border-default px-6 py-5">
        <h2 className="font-heading text-lg font-bold tracking-tight text-foreground">
          Non-Disclosure Agreement
        </h2>
      </div>
      <div className="space-y-4 p-6">
        {isSigned ? (
          <div className="rounded-xl border border-success/30 bg-success/10 p-4 text-success">
            <p className="font-semibold">NDA Signed</p>
            <p className="mt-1 text-sm">
              You have signed the latest version ({nda.current_version}) of the NDA on{" "}
              {nda.signed_at ? new Date(nda.signed_at).toLocaleDateString() : "unknown date"}.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-4 text-warning">
            <p className="font-semibold">Signature Required</p>
            <p className="mt-1 text-sm">
              You must sign the latest NDA (version {nda.current_version}) to participate in attestations and access confidential materials.
            </p>
          </div>
        )}

        <div className="h-64 overflow-y-auto whitespace-pre-wrap rounded-xl border border-border-default bg-surface-2 p-4 text-sm leading-6 text-foreground-muted">
          {nda.document}
        </div>
      </div>
      {!isSigned && (
        <div className="flex justify-end gap-2 border-t border-border-default bg-surface-2/50 p-6">
          <Button className="min-h-12 w-full sm:w-auto" onClick={handleSign} disabled={signing}>
            {signing ? "Signing..." : "Sign NDA"}
          </Button>
        </div>
      )}
    </section>
  );
}
