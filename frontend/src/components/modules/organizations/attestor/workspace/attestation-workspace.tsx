"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftIcon } from "@radix-ui/react-icons";
import {
  getAttestation,
  startAttestationReview,
  listOrgAttestations
} from "@/lib/generated/sdk.gen";
import type { AttestationRequestResponse, OrgAttestationItem } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { Spinner } from "@/components/ui/spinner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ExclamationTriangleIcon, CheckCircledIcon } from "@radix-ui/react-icons";
import { RubricPanel } from "./rubric-panel";
import { AnnotationsPanel } from "./annotations-panel";
import { ClarificationsPanel } from "./clarifications-panel";
import { ReportPanel } from "./report-panel";

type AttestationWorkspaceProps = {
  orgId: string;
  attestationId: string;
};

export function AttestationWorkspace({ orgId, attestationId }: AttestationWorkspaceProps) {
  const router = useRouter();
  const { memberId } = useOrganization() as { memberId?: string, role: string };
  const [attestation, setAttestation] = useState<AttestationRequestResponse | null>(null);
  const [queueItem, setQueueItem] = useState<OrgAttestationItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [res, queueRes] = await Promise.all([
        getAttestation({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders()
        }),
        listOrgAttestations({
          path: { org_id: orgId },
          headers: getAccessTokenHeaders()
        })
      ]);
      
      if (res.error) throw new Error(describeGeneratedError(res.error));
      if (queueRes.error) throw new Error(describeGeneratedError(queueRes.error));
      
      const foundQueueItem = queueRes.data.attestations.find(
        (item: OrgAttestationItem) => item.id === attestationId,
      );
      
      setAttestation(res.data);
      setQueueItem(foundQueueItem || null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load attestation.");
    } finally {
      setLoading(false);
    }
  }

    useEffect(() => {
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attestationId, orgId]);

  if (loading) {
    return <div className="p-8 flex justify-center"><Spinner className="h-8 w-8 text-accent" /></div>;
  }

  if (error || !attestation) {
    return (
      <div className="p-8 flex items-center justify-center gap-2 text-error">
        <ExclamationTriangleIcon className="h-5 w-5" />
        {error || "Attestation not found."}
      </div>
    );
  }

  // The current member can write if they are exactly the assigned reviewing member
  const canWrite = Boolean(memberId && queueItem?.reviewing_member_id === memberId);
  // The review is "started" once it moves past the freshly-accepted state.
  const isStarted = attestation.status !== "accepted";
  const showStartReview = canWrite && !isStarted;
  const frameworkLabel = queueItem?.target_title ?? attestation.target_type;
  const reviewerLabel = queueItem?.reviewing_member_name ?? "Unassigned";

  async function handleStartReview() {
    setStarting(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await startAttestationReview({
        path: { attestation_id: attestationId },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error(describeGeneratedError(res.error));
      setActionSuccess("Review started.");
      await load();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Failed to start review.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="space-y-6">
      <button
        className="inline-flex items-center gap-2 text-sm font-semibold text-foreground-muted outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
        onClick={() => router.push(`/dashboard/organizations/${orgId}/queue`)}
        type="button"
      >
        <ArrowLeftIcon className="h-4 w-4" /> Back to queue
      </button>

      {/* Header Card */}
      <div className="rounded-2xl border border-foreground/10 bg-background shadow-bento">
        <div className="flex flex-row items-center justify-between border-b border-foreground/5 p-6 pb-4">
          <div>
            <h2 className="text-xl font-bold font-heading">{frameworkLabel}</h2>
            <p className="text-sm text-foreground-muted mt-1 capitalize">
              {attestation.review_type ? `${attestation.review_type} review` : "Attestation"}
              {" · "}
              {attestation.target_type}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="default" className="capitalize">{attestation.status.replace("_", " ")}</Badge>
            {showStartReview && (
              <Button onClick={handleStartReview} disabled={starting} loading={starting}>
                Start Review
              </Button>
            )}
          </div>
        </div>
        {actionError && (
          <div className="mx-6 mb-4 rounded-xl border border-error/50 bg-error/5 p-4 flex items-center gap-2 text-sm text-error">
            <ExclamationTriangleIcon className="h-4 w-4" />
            {actionError}
          </div>
        )}
        {actionSuccess && (
          <div className="mx-6 mb-4 rounded-xl border border-success/50 bg-success/5 p-4 flex items-center gap-2 text-sm text-success">
            <CheckCircledIcon className="h-4 w-4" />
            {actionSuccess}
          </div>
        )}
        <div className="p-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="block text-foreground-muted mb-1">Review Type</span>
              <span className="font-semibold capitalize">{attestation.review_type}</span>
            </div>
            <div>
              <span className="block text-foreground-muted mb-1">Assigned Member</span>
              <span className="font-semibold">{reviewerLabel}</span>
            </div>
            <div>
              <span className="block text-foreground-muted mb-1">Started</span>
              <span className="font-semibold">
                {isStarted ? "Yes" : "Not started"}
              </span>
            </div>
            <div>
              <span className="block text-foreground-muted mb-1">Access</span>
              <span className={`font-semibold ${canWrite ? "text-accent" : "text-foreground-muted"}`}>
                {canWrite ? "Write" : "Read-only"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Workspace Panels Stub */}
      {isStarted && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <RubricPanel 
              attestationId={attestationId} 
              reviewType={attestation.review_type || ""} 
              canWrite={canWrite} 
            />
            <AnnotationsPanel 
              attestationId={attestationId} 
              canWrite={canWrite} 
            />
          </div>
          <div className="space-y-6">
            <ClarificationsPanel 
              attestationId={attestationId} 
              canWrite={canWrite} 
            />
            <ReportPanel 
              attestationId={attestationId}
              canWrite={canWrite}
              orgId={orgId}
            />
          </div>
        </div>
      )}
    </div>
  );
}

