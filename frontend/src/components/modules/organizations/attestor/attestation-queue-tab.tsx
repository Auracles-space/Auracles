"use client";

import { useState, useEffect } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { listOrgAttestationsV1OrgsOrgIdAttestationsGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgAttestationItem } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { ReassignReviewerDialog } from "./reassign-reviewer-dialog";

// In-flight assignment statuses — mirrors the backend _IN_FLIGHT_REVIEW_STATUSES
// used for the Queue tab count, so the badge and the list always agree.
const ACTIVE_QUEUE_STATUSES = [
  "accepted",
  "in_review",
  "report_submitted",
  "revision_requested",
  "disputed",
];

/** Badge variant for an in-flight attestation status. */
function queueStatusVariant(
  status: string,
): "info" | "default" | "warning" | "error" {
  if (status === "accepted") return "info";
  if (status === "disputed") return "error";
  if (status === "in_review") return "default";
  return "warning";
}

export function AttestationQueueTab() {
  const { orgId, role } = useOrganization();
  const [attestations, setAttestations] = useState<OrgAttestationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reassigningId, setReassigningId] = useState<string | null>(null);

  async function load(isMounted: () => boolean) {
    setLoading(true);
    setError(null);
    const res = await listOrgAttestationsV1OrgsOrgIdAttestationsGet({
      path: { org_id: orgId! },
      headers: getAccessTokenHeaders(),
    });
    if (!isMounted()) return;
    setLoading(false);
    if (res.error) {
      setError(describeGeneratedError(res.error));
    } else if (res.data) {
      setAttestations(res.data.attestations);
    }
  }

  useEffect(() => {
    let mounted = true;
    if (!orgId) return;

    const doLoad = async () => {
      setLoading(true);
      await load(() => mounted);
      if (mounted) setLoading(false);
    };
    doLoad();
    return () => { mounted = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (loading) {
    return <div className="p-4 flex items-center gap-2 text-sm text-foreground-muted"><Spinner className="w-4 h-4" /> Loading queue...</div>;
  }

  if (error) {
    return <div className="p-4 text-sm text-error bg-error/5 border border-error/20 rounded-md">{error}</div>;
  }

  const activeAttestations = attestations.filter((a) =>
    ACTIVE_QUEUE_STATUSES.includes(a.status),
  );

  if (activeAttestations.length === 0) {
    return (
      <div className="p-8 text-center text-foreground-muted border border-border-default border-dashed rounded-xl bg-surface-2">
        <h3 className="font-semibold text-foreground mb-1">Queue Empty</h3>
        <p className="text-sm">There are no active attestations in your queue.</p>
      </div>
    );
  }

  const isAdmin = role === "admin" || role === "owner";

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Attestation Queue</h2>
      </div>
      
      <div className="grid gap-4">
        {activeAttestations.map((att) => (
          <div key={att.id} className="border border-border-default rounded-xl p-5 bg-surface-1 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground capitalize">{att.target_type}</span>
                <Badge variant={queueStatusVariant(att.status)}>
                  {att.status.replace("_", " ")}
                </Badge>
              </div>
              <div className="text-sm text-foreground-muted font-mono">
                Attestation ID: {att.id}
              </div>
              {isAdmin && (
                <div className="text-sm text-foreground-muted">
                  Assigned to: {att.reviewing_member_id || "Unassigned"}
                </div>
              )}
            </div>
            
            <div className="flex flex-col sm:flex-row gap-2">
              <Button 
                variant="secondary"
                disabled={!isAdmin}
                onClick={() => setReassigningId(att.id)}
              >
                Reassign
              </Button>
              <Button
                variant="secondary"
                onClick={() => window.location.href = `/dashboard/organizations/${orgId}/attestations/${att.id}`}
              >
                Workspace
              </Button>
            </div>
          </div>
        ))}
      </div>

      {reassigningId && orgId && (
        <ReassignReviewerDialog
          orgId={orgId}
          attestationId={reassigningId}
          onClose={() => setReassigningId(null)}
          onDone={() => {
            setReassigningId(null);
            load(() => true);
          }}
        />
      )}
    </div>
  );
}
