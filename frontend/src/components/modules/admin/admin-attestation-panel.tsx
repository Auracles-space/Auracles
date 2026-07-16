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
  adminAssignAttestation,
  adminRefundAttestation,
  listAdminAttestations,
  listOrgAttestorApplicationsForAdmin,
  rejectOrgAttestor,
  resolveAttestationDispute,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  OrgAttestorApplicationResponse,
} from "@/lib/generated/types.gen";
import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import {
  ErrorMessage,
  HeaderCard,
  StatusTag,
} from "@/components/modules/attestation/attestation-status";

export function AdminAttestationPanel() {
  const [applications, setApplications] = useState<OrgAttestorApplicationResponse[]>([]);
  const [needsAdmin, setNeedsAdmin] = useState<AttestationRequestResponse[]>([]);
  const [assignAttestationId, setAssignAttestationId] = useState("");
  const [assignAttestorOrgId, setAssignAttestorOrgId] = useState("");
  const [assignReviewingMemberId, setAssignReviewingMemberId] = useState("");
  const [disputeId, setDisputeId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refundAmount, setRefundAmount] = useState("");
  const [releaseAmount, setReleaseAmount] = useState("");
  const [resolutionType, setResolutionType] =
    useState<"release" | "refund" | "split">("release");
  const [manualReason, setManualReason] = useState("");
  const [totpCode, setTotpCode] = useState("");
  
  const hasTotp = totpCode.trim().length >= 6;
  const canAssign = allValid(
    isNonEmpty(assignAttestationId),
    isNonEmpty(assignAttestorOrgId),
    isNonEmpty(assignReviewingMemberId),
    isNonEmpty(manualReason),
    hasTotp,
  );
  const canRefund = allValid(
    isNonEmpty(assignAttestationId),
    isNonEmpty(manualReason),
    hasTotp,
  );
  const canResolveDispute = allValid(
    isNonEmpty(disputeId),
    isNonEmpty(manualReason),
    hasTotp,
    resolutionType !== "split" ||
      allValid(isPositiveNumber(releaseAmount), isPositiveNumber(refundAmount)),
  );

  useEffect(() => {
    void loadApplications();
    void loadNeedsAdmin();
  }, []);

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

  /** Load the needs-admin attestation queue for manual assign/refund. */
  async function loadNeedsAdmin() {
    configureBrowserClient();
    const result = await listAdminAttestations({
      headers: getAccessTokenHeaders(),
      query: { status: "needs_admin" },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setNeedsAdmin(result.data.attestations);
  }

  async function handleReview(application: OrgAttestorApplicationResponse) {
    setError(null);
    configureBrowserClient();
    const result = await rejectOrgAttestor({
      body: { feedback: manualReason },
      headers: getAccessTokenHeaders(),
      path: { application_id: application.id },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications((current) => current.filter((item) => item.id !== application.id));
  }

  async function handleManualAssign() {
    setError(null);
    configureBrowserClient();
    const result = await adminAssignAttestation({
      body: {
        attestor_org_id: assignAttestorOrgId,
        reviewing_member_id: assignReviewingMemberId,
        reason: manualReason,
        totp_code: totpCode,
      },
      headers: getAccessTokenHeaders(),
      path: { attestation_id: assignAttestationId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
    }
  }

  async function handleAdminRefund() {
    setError(null);
    configureBrowserClient();
    const result = await adminRefundAttestation({
      body: { reason: manualReason, totp_code: totpCode },
      headers: getAccessTokenHeaders(),
      path: { attestation_id: assignAttestationId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
    }
  }

  async function handleResolveDispute() {
    setError(null);
    configureBrowserClient();
    const result = await resolveAttestationDispute({
      body: {
        outcome: resolutionType === "refund" ? "upheld_refund" : "rejected",
        resolution_notes: manualReason,
        totp_code: totpCode,
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
      
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h3 className="font-heading text-lg font-bold text-foreground mb-4">
          Audit & Security Context
        </h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Admin 2FA code
            <Input 
              onChange={(event) => setTotpCode(event.target.value)} 
              placeholder="Enter 6-digit code"
              value={totpCode} 
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Reason or notes
            <Input 
              onChange={(event) => setManualReason(event.target.value)} 
              placeholder="Explain this action for audit logs..."
              value={manualReason} 
            />
          </label>
        </div>
      </div>

      <div className="grid gap-3">
        {applications.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
            No applications to show.
          </p>
        ) : (
          applications.map((application) => (
            <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm" key={application.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="grid gap-2">
                  <h3 className="font-heading text-lg font-bold text-foreground">
                    Attestor Application
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {application.jurisdictions?.map((jur: string) => (
                      <span
                        key={jur}
                        className="inline-flex items-center rounded-lg border border-accent/20 bg-accent/5 px-2 py-0.5 text-xs font-semibold text-accent"
                      >
                        {jur}
                      </span>
                    ))}
                  </div>
                </div>
                <StatusTag value={application.status} />
              </div>
              
              <div className="mt-4 grid gap-3 border-t border-border-default pt-4">
                <div className="grid gap-1">
                  <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-muted">
                    Credentials Summary
                  </span>
                  <p className="text-sm leading-relaxed text-foreground">
                    {application.credentials_summary}
                  </p>
                </div>
                {application.professional_references ? (
                  <div className="grid gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-muted">
                      Professional References
                    </span>
                    <p className="text-sm leading-relaxed text-foreground-muted">
                      {application.professional_references}
                    </p>
                  </div>
                ) : null}
              </div>

              {application.status === "rejected" ? (
                <p className="mt-3 rounded-xl border border-error/30 bg-error/5 px-4 py-3 text-sm text-error font-medium">
                  Rejected.{" "}
                  {application.admin_feedback
                    ? application.admin_feedback
                    : "No reason was provided. You can submit a new application."}
                </p>
              ) : null}
              {application.status === "active" ? (
                <p className="mt-3 rounded-xl border border-success/30 bg-success/5 px-4 py-3 text-sm text-success font-medium">
                  Active.{" "}
                  {application.admin_feedback ?? "Your attestor access is active."}
                </p>
              ) : null}
              <div className="mt-4 flex flex-wrap gap-3">
                {application.status !== "active" && application.status !== "rejected" ? (
                  <>
                    <button className="min-h-12 rounded-xl border border-error px-5 text-sm font-semibold text-error shadow-sm outline-none transition-all hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-50" disabled={!hasTotp} onClick={() => handleReview(application)} type="button">
                      Reject
                    </button>
                    {!hasTotp ? (
                      <p className="w-full text-xs text-foreground-muted">
                        Enter your 6-digit 2FA code above to reject.
                      </p>
                    ) : null}
                  </>
                ) : null}
              </div>
            </article>
          ))
        )}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h3 className="font-heading text-lg font-bold text-foreground">
          Needs admin{needsAdmin.length > 0 ? ` (${needsAdmin.length})` : ""}
        </h3>
        <p className="mt-1 text-sm text-foreground-muted">
          Requests auto-matching could not staff. Load one into the controls
          below to assign an attestor or refund the fee.
        </p>
        <div className="mt-4 grid gap-3">
          {needsAdmin.length === 0 ? (
            <p className="text-sm text-foreground-muted">
              No requests are waiting for admin action.
            </p>
          ) : (
            needsAdmin.map((item) => (
              <article
                className="grid gap-3 rounded-xl border border-border-default bg-surface-1 p-4 shadow-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
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
                <button
                  className="min-h-11 rounded-xl border border-border-default px-4 text-sm font-semibold text-foreground outline-none transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
                  onClick={() => setAssignAttestationId(item.id)}
                  type="button"
                >
                  Load into controls
                </button>
              </article>
            ))
          )}
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-heading text-xl font-bold text-foreground mb-2">
              Attestation Controls
            </h3>
            <p className="text-xs text-foreground-muted mb-4 leading-relaxed">
              Manually assign pending requests to qualified attestors, or cancel the request and refund operators.
            </p>
            <div className="grid gap-4 mb-6">
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Attestation ID
                <Input 
                  onChange={(event) => setAssignAttestationId(event.target.value)} 
                  placeholder="e.g. att-93f8e" 
                  value={assignAttestationId} 
                />
              </label>
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Target Attestor Org ID
                <Input 
                  onChange={(event) => setAssignAttestorOrgId(event.target.value)} 
                  placeholder="Required for manual assignment" 
                  value={assignAttestorOrgId} 
                />
              </label>
              <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                Target Reviewing Member ID
                <Input 
                  onChange={(event) => setAssignReviewingMemberId(event.target.value)} 
                  placeholder="Required for manual assignment" 
                  value={assignReviewingMemberId} 
                />
              </label>
            </div>
          </div>
          <div className="flex flex-wrap gap-3 pt-4 border-t border-border-default/40">
            <Button 
              disabled={!canAssign} 
              onClick={handleManualAssign} 
              type="button"
            >
              Manual assign
            </Button>
            <Button 
              disabled={!canRefund} 
              onClick={handleAdminRefund} 
              type="button"
              variant="destructive"
            >
              Refund request
            </Button>
          </div>
        </div>

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
