"use client";

import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  listAdminAttestations,
  listAttestorOrgs,
  listOrgAttestorApplicationsForAdmin,
  resolveAttestationDispute,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  AttestorDirectoryEntry,
  OrgAttestorApplicationResponse,
} from "@/lib/generated/types.gen";
import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import {
  ErrorMessage,
  HeaderCard,
  StatusTag,
} from "@/components/modules/attestation/attestation-status";
import { NeedsAdminRow } from "@/components/modules/admin/needs-admin-row";
import { AttestorApplicationRow } from "@/components/modules/admin/attestor-application-row";
import { emitNeedsAdminChanged } from "@/components/modules/admin/admin-events";

export function AdminAttestationPanel() {
  const [applications, setApplications] = useState<OrgAttestorApplicationResponse[]>([]);
  const [queueItems, setQueueItems] = useState<AttestationRequestResponse[]>([]);
  const [queueStatus, setQueueStatus] = useState("needs_admin");
  const [attestorOrgs, setAttestorOrgs] = useState<AttestorDirectoryEntry[]>([]);
  const [disputeId, setDisputeId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refundAmount, setRefundAmount] = useState("");
  const [releaseAmount, setReleaseAmount] = useState("");
  const [resolutionType, setResolutionType] =
    useState<"release" | "refund" | "split">("release");
  const [disputeReason, setDisputeReason] = useState("");
  const [disputeTotp, setDisputeTotp] = useState("");

  const canResolveDispute = allValid(
    isNonEmpty(disputeId),
    isNonEmpty(disputeReason),
    disputeTotp.trim().length >= 6,
    resolutionType !== "split" ||
      allValid(isPositiveNumber(releaseAmount), isPositiveNumber(refundAmount)),
  );

  useEffect(() => {
    void loadApplications();
    void loadAttestorOrgs();
  }, []);

  useEffect(() => {
    void loadQueue(queueStatus);
  }, [queueStatus]);

  /** Load active attestor orgs for the manual-assign org picker. */
  async function loadAttestorOrgs() {
    configureBrowserClient();
    const result = await listAttestorOrgs({ headers: getAccessTokenHeaders() });
    if (result.response.ok && result.data) {
      setAttestorOrgs(result.data.attestors);
    }
  }

  async function loadApplications() {
    configureBrowserClient();
    const result = await listOrgAttestorApplicationsForAdmin({
      headers: getAccessTokenHeaders(),
      query: { status: "submitted" },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications(result.data.applications);
  }

  /** Load attestations in the given status for the admin queue/history. */
  async function loadQueue(status: string) {
    configureBrowserClient();
    const result = await listAdminAttestations({
      headers: getAccessTokenHeaders(),
      query: { status },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setQueueItems(result.data.attestations);
  }

  /** Drop an application from the list once it is rejected. */
  function handleApplicationRejected(applicationId: string) {
    setApplications((current) =>
      current.filter((item) => item.id !== applicationId),
    );
  }

  /** Drop a request from the queue once it is assigned or refunded. */
  function handleNeedsAdminResolved(attestationId: string) {
    setQueueItems((current) =>
      current.filter((item) => item.id !== attestationId),
    );
    // Let the workspace shell refresh its needs-admin count badge.
    emitNeedsAdminChanged();
  }

  async function handleResolveDispute() {
    setError(null);
    configureBrowserClient();
    const result = await resolveAttestationDispute({
      body: {
        outcome: resolutionType === "refund" ? "upheld_refund" : "rejected",
        resolution_notes: disputeReason,
        totp_code: disputeTotp,
      },
      headers: getAccessTokenHeaders(),
      path: { dispute_id: disputeId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
    }
  }

  return (
    <section className="grid gap-6">
      <HeaderCard
        eyebrow="Admin attestation"
        title="Review and resolution"
        summary="Review Attestor applications, manually assign exhausted requests, refund needs-admin requests, or resolve disputes."
      />
      
      <ErrorMessage message={error} />

      <div className="grid gap-3">
        {applications.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
            No applications to show.
          </p>
        ) : (
          applications.map((application) => (
            <AttestorApplicationRow
              application={application}
              key={application.id}
              onRejected={handleApplicationRejected}
            />
          ))
        )}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-heading text-lg font-bold text-foreground">
            Attestations
            {queueStatus === "needs_admin" && queueItems.length > 0
              ? ` (${queueItems.length})`
              : ""}
          </h3>
          <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
            Status
            <Select
              onChange={(event) => setQueueStatus(event.target.value)}
              value={queueStatus}
            >
              <option value="needs_admin">Needs admin</option>
              <option value="offered">Offered (assigned)</option>
              <option value="accepted">Accepted</option>
              <option value="in_review">In review</option>
              <option value="report_submitted">Report submitted</option>
              <option value="closed">Closed / refunded</option>
            </Select>
          </label>
        </div>
        <p className="mt-1 text-sm text-foreground-muted">
          {queueStatus === "needs_admin"
            ? "Requests auto-matching could not staff. Assign each to an attestor org (the org then staffs its own reviewer) or refund the fee — inline."
            : "Read-only view of attestations in this status."}
        </p>
        <div className="mt-4 grid gap-3">
          {queueItems.length === 0 ? (
            <p className="text-sm text-foreground-muted">
              No attestations in this status.
            </p>
          ) : queueStatus === "needs_admin" ? (
            queueItems.map((item) => (
              <NeedsAdminRow
                attestation={item}
                attestorOrgs={attestorOrgs}
                key={item.id}
                onResolved={handleNeedsAdminResolved}
              />
            ))
          ) : (
            queueItems.map((item) => (
              <article
                className="grid gap-2 rounded-xl border border-border-default bg-surface-1 p-4 shadow-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                key={item.id}
              >
                <div>
                  <p className="font-heading text-sm font-bold text-foreground">
                    {item.review_type
                      ? `${item.review_type} review`
                      : "Attestation request"}
                  </p>
                  <p className="mt-1 text-xs text-foreground-muted">
                    {item.id} · {item.currency} {item.fee_amount}
                  </p>
                </div>
                <StatusTag value={item.status} />
              </article>
            ))
          )}
        </div>
      </div>

      <div className="grid gap-6">
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-heading text-xl font-bold text-foreground mb-2">
              Dispute Resolution
            </h3>
            <p className="text-xs text-foreground-muted mb-4 leading-relaxed">
              Resolve formal quality or service disputes by releasing funds to the contributor, refunding the operator, or dividing the escrow.
            </p>
            <div className="grid gap-4 mb-6">
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Dispute ID
                <Input 
                  onChange={(event) => setDisputeId(event.target.value)} 
                  placeholder="e.g. dsp-18a7b" 
                  value={disputeId} 
                />
              </label>
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Resolution Strategy
                <Select 
                  onChange={(event) => setResolutionType(event.target.value as "release" | "refund" | "split")} 
                  value={resolutionType}
                >
                  <option value="release">Release (Pay Contributor)</option>
                  <option value="refund">Refund (Pay Operator)</option>
                  <option value="split">Split Escrow Funds</option>
                </Select>
              </label>
              
              {resolutionType === "split" && (
                <div className="grid gap-3 sm:grid-cols-2 rounded-xl bg-surface-2 p-3 border border-border-default">
                  <label className="grid gap-1.5 text-xs font-semibold text-foreground">
                    Release to Contributor ($)
                    <Input 
                      className="min-h-11 rounded-lg border border-border-default bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent" 
                      onChange={(event) => setReleaseAmount(event.target.value)} 
                      placeholder="Amount" 
                      value={releaseAmount} 
                    />
                  </label>
                  <label className="grid gap-1.5 text-xs font-semibold text-foreground">
                    Refund to Operator ($)
                    <Input 
                      className="min-h-11 rounded-lg border border-border-default bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent" 
                      onChange={(event) => setRefundAmount(event.target.value)} 
                      placeholder="Amount" 
                      value={refundAmount} 
                    />
                  </label>
                </div>
              )}
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Resolution notes
                <Input
                  onChange={(event) => setDisputeReason(event.target.value)}
                  placeholder="Explain this resolution for audit logs"
                  value={disputeReason}
                />
              </label>
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Admin 2FA code
                <Input
                  inputMode="numeric"
                  onChange={(event) => setDisputeTotp(event.target.value)}
                  placeholder="6-digit code"
                  value={disputeTotp}
                />
              </label>
            </div>
          </div>
          <div className="pt-4 border-t border-border-default/40">
            <Button
              className="w-full sm:w-auto"
              disabled={!canResolveDispute}
              onClick={handleResolveDispute}
              type="button"
            >
              Resolve dispute
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
