"use client";

import { useState, useEffect } from "react";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { getOrgNda, signOrgNda } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgNdaStatusResponse } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";

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
    }
  };

  if (loading) {
    return <div className="p-4 text-sm text-neutral-500">Loading NDA status...</div>;
  }

  if (error) {
    return <div className="p-4 text-sm text-red-500">{error}</div>;
  }

  if (!nda || !nda.required) {
    return <div className="p-4 text-sm text-neutral-500">No NDA is required for this organization at this time.</div>;
  }

  const isSigned = nda.signed_version === nda.current_version;

  return (
    <div className="w-full max-w-2xl border rounded-lg overflow-hidden bg-white shadow-sm">
      <div className="p-6 border-b border-neutral-200">
        <h2 className="text-lg font-semibold tracking-tight text-neutral-900">Non-Disclosure Agreement</h2>
      </div>
      <div className="p-6 space-y-4">
        {isSigned ? (
          <div className="bg-green-50 text-green-700 p-4 rounded-md border border-green-100">
            <p className="font-medium">NDA Signed</p>
            <p className="text-sm mt-1">You have signed the latest version ({nda.current_version}) of the NDA on {nda.signed_at ? new Date(nda.signed_at).toLocaleDateString() : "unknown date"}.</p>
          </div>
        ) : (
          <div className="bg-amber-50 text-amber-800 p-4 rounded-md border border-amber-100">
            <p className="font-medium">Signature Required</p>
            <p className="text-sm mt-1">
              You must sign the latest NDA (version {nda.current_version}) to participate in attestations and access confidential materials.
            </p>
          </div>
        )}

        <div className="border border-neutral-200 rounded-md p-4 bg-neutral-50 text-sm h-64 overflow-y-auto whitespace-pre-wrap font-mono text-neutral-700">
          {/* We do not receive the actual NDA text from the endpoint, so we show a placeholder for now */}
          [Confidentiality Agreement Text Placeholder for version {nda.current_version}]
          
          The Recipient agrees not to disclose any Confidential Information to third parties...
          (Full legal text would be fetched and displayed here)
        </div>
      </div>
      {!isSigned && (
        <div className="flex justify-end gap-2 border-t border-neutral-200 p-6 bg-neutral-50/50">
          <Button onClick={handleSign} disabled={signing}>
            {signing ? "Signing..." : "Sign NDA"}
          </Button>
        </div>
      )}
    </div>
  );
}
