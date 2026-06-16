"use client";

/**
 * Attestation workflow panels.
 *
 * These client components cover Slice 12 frontend wiring for requestors,
 * attestors, and admins using only generated OpenAPI client functions.
 */
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  acceptAttestationOffer,
  acceptAttestationReport,
  adminAssignAttestation,
  adminRefundAttestation,
  createAttestationDispute,
  declineAttestationOffer,
  listAttestations,
  listAttestorApplicationsForAdmin,
  listAttestorAssignments,
  listMyAttestorApplications,
  requestAttestation,
  resolveAttestationDispute,
  reviewAttestorApplication,
  submitAttestationReport,
  submitAttestorApplication,
  withdrawAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  AttestorApplicationResponse,
  AttestorAssignmentResponse,
} from "@/lib/generated/types.gen";
import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

/**
 * Render a compact status tag.
 *
 * @param value - Raw status value from the API.
 */
function StatusTag({ value }: { value: string }) {
  return (
    <span className="inline-flex rounded-md border border-info/30 bg-info/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-info">
      {formatLabel(value)}
    </span>
  );
}

/**
 * Convert comma-separated user input into API array fields.
 *
 * @param value - Comma-separated text.
 */
function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Show user-facing request errors.
 */
function ErrorMessage({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  return <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">{message}</p>;
}

/**
 * Render requestor-side Attestation request and lifecycle controls.
 */
export function AttestationRequestorPanel() {
  const [attestations, setAttestations] = useState<AttestationRequestResponse[]>([]);
  const [disputeReason, setDisputeReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jurisdictions, setJurisdictions] = useState("");
  const [loading, setLoading] = useState(true);
  const [specializations, setSpecializations] = useState("");
  const [targetId, setTargetId] = useState("");
  const [targetType, setTargetType] =
    useState<"framework" | "contributor" | "operator" | "credential">("framework");
  const canRequest = allValid(
    isNonEmpty(targetId),
    isNonEmpty(specializations),
    isNonEmpty(jurisdictions),
  );
  const canDispute = isNonEmpty(disputeReason);

  useEffect(() => {
    void loadRequestorAttestations();
  }, []);

  /**
   * Load requestor-visible Attestations.
   */
  async function loadRequestorAttestations() {
    configureBrowserClient();
    const result = await listAttestations({
      headers: getAccessTokenHeaders(),
      query: { role: "requestor" },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return;
    }
    setAttestations(result.data.attestations);
    setLoading(false);
  }

  /**
   * Create a new escrow-funded Attestation request.
   */
  async function handleRequestAttestation() {
    setError(null);
    configureBrowserClient();
    const result = await requestAttestation({
      body: {
        requested_jurisdictions: splitCsv(jurisdictions),
        requested_specializations: splitCsv(specializations),
        target_id: targetId,
        target_type: targetType,
      },
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setTargetId("");
    await loadRequestorAttestations();
  }

  /**
   * Accept a submitted report and release escrow.
   *
   * @param attestationId - Attestation UUID.
   */
  async function handleAcceptReport(attestationId: string) {
    setError(null);
    configureBrowserClient();
    const result = await acceptAttestationReport({
      headers: getAccessTokenHeaders(),
      path: { attestation_id: attestationId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setAttestations((current) =>
      current.map((item) => (item.id === attestationId ? result.data : item)),
    );
  }

  /**
   * Raise a dispute against a submitted report.
   *
   * @param attestationId - Attestation UUID.
   */
  async function handleDispute(attestationId: string) {
    setError(null);
    configureBrowserClient();
    const result = await createAttestationDispute({
      body: { reason: disputeReason },
      headers: getAccessTokenHeaders(),
      path: { attestation_id: attestationId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setDisputeReason("");
    await loadRequestorAttestations();
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <HeaderCard
        eyebrow="Requestor workspace"
        title="Attestation requests"
        summary="Request independent verification, inspect reports, accept outcomes, or dispute within the open window."
      />
      <ErrorMessage message={error} />

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Request Attestation
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Target type
            <select
              className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) =>
                setTargetType(
                  event.target.value as
                    | "framework"
                    | "contributor"
                    | "operator"
                    | "credential",
                )
              }
              value={targetType}
            >
              <option value="framework">Framework</option>
              <option value="contributor">Contributor profile</option>
              <option value="operator">Operator organization</option>
              <option value="credential">Credential</option>
            </select>
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Target ID
            <input
              className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setTargetId(event.target.value)}
              value={targetId}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Specializations
            <input
              className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setSpecializations(event.target.value)}
              placeholder="governance, healthcare"
              value={specializations}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Jurisdictions
            <input
              className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setJurisdictions(event.target.value)}
              placeholder="US, EU"
              value={jurisdictions}
            />
          </label>
        </div>
        <button
          className="mt-6 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canRequest}
          onClick={handleRequestAttestation}
          type="button"
        >
          Start fee escrow
        </button>
      </div>

      <div className="grid gap-3">
        {attestations.map((attestation) => (
          <AttestationCard attestation={attestation} key={attestation.id}>
            {attestation.status === "report_submitted" ? (
              <div className="mt-4 grid gap-3">
                <button
                  className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
                  onClick={() => handleAcceptReport(attestation.id)}
                  type="button"
                >
                  Accept report
                </button>
                <label className="grid gap-2 text-sm font-semibold text-foreground">
                  Dispute reason
                  <textarea
                    className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
                    onChange={(event) => setDisputeReason(event.target.value)}
                    value={disputeReason}
                  />
                </label>
                <button
                  className="min-h-12 rounded-xl border border-error/50 bg-error/5 px-6 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!canDispute}
                  onClick={() => handleDispute(attestation.id)}
                  type="button"
                >
                  Raise dispute
                </button>
              </div>
            ) : null}
          </AttestationCard>
        ))}
      </div>
    </section>
  );
}

/**
 * Render Attestor application history and submission form.
 */
export function AttestorApplicationPanel() {
  const [applications, setApplications] = useState<AttestorApplicationResponse[]>([]);
  const [credentialsSummary, setCredentialsSummary] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jurisdictions, setJurisdictions] = useState("");
  const [loading, setLoading] = useState(true);
  const [professionalReferences, setProfessionalReferences] = useState("");
  const [specializations, setSpecializations] = useState("");
  const canSubmit = allValid(
    isNonEmpty(specializations),
    isNonEmpty(jurisdictions),
    isNonEmpty(credentialsSummary),
    isNonEmpty(professionalReferences),
  );

  useEffect(() => {
    void loadApplications();
  }, []);

  /**
   * Load application history for the current user.
   */
  async function loadApplications() {
    configureBrowserClient();
    const result = await listMyAttestorApplications({
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return;
    }
    setApplications(result.data.applications);
    setLoading(false);
  }

  /**
   * Submit an Attestor application.
   */
  async function handleSubmitApplication() {
    setError(null);
    configureBrowserClient();
    const result = await submitAttestorApplication({
      body: {
        credentials_summary: credentialsSummary,
        jurisdictions: splitCsv(jurisdictions),
        professional_references: professionalReferences,
        sample_work: {},
        specializations: splitCsv(specializations),
      },
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications((current) => [result.data, ...current]);
  }

  /**
   * Withdraw a pending Attestor application.
   *
   * @param applicationId - Application UUID.
   */
  async function handleWithdraw(applicationId: string) {
    setError(null);
    configureBrowserClient();
    const result = await withdrawAttestorApplication({
      headers: getAccessTokenHeaders(),
      path: { application_id: applicationId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications((current) =>
      current.map((item) => (item.id === applicationId ? result.data : item)),
    );
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <HeaderCard
        eyebrow="Attestor onboarding"
        title="Attestor application"
        summary="Apply to receive verification assignments matched to your specialization and jurisdiction."
      />
      <ErrorMessage message={error} />
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Specializations
            <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setSpecializations(event.target.value)} value={specializations} />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Jurisdictions
            <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setJurisdictions(event.target.value)} value={jurisdictions} />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground md:col-span-2">
            Credentials summary
            <textarea className="min-h-28 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setCredentialsSummary(event.target.value)} value={credentialsSummary} />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground md:col-span-2">
            Professional references
            <textarea className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setProfessionalReferences(event.target.value)} value={professionalReferences} />
          </label>
        </div>
        <button className="mt-6 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={!canSubmit} onClick={handleSubmitApplication} type="button">
          Submit application
        </button>
      </div>
      <ApplicationList applications={applications} onWithdraw={handleWithdraw} />
    </section>
  );
}

/**
 * Render Attestor offers, accepted assignments, and report submission controls.
 */
export function AttestorAssignmentsPanel() {
  const [assignments, setAssignments] = useState<AttestorAssignmentResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] =
    useState<"approved" | "conditional" | "rejected">("approved");
  const [scope, setScope] = useState("");
  const [summary, setSummary] = useState("");
  const canSubmitReport = allValid(isNonEmpty(summary), isNonEmpty(scope));

  useEffect(() => {
    void loadAssignments();
  }, []);

  /**
   * Load attestor assignment queue.
   */
  async function loadAssignments() {
    configureBrowserClient();
    const result = await listAttestorAssignments({
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setAssignments(result.data.assignments);
  }

  /**
   * Accept or decline one offered Attestation.
   *
   * @param assignment - Assignment row.
   * @param decision - Offer response.
   */
  async function handleOffer(
    assignment: AttestorAssignmentResponse,
    decision: "accept" | "decline",
  ) {
    setError(null);
    configureBrowserClient();
    const call = decision === "accept" ? acceptAttestationOffer : declineAttestationOffer;
    const result = await call({
      headers: getAccessTokenHeaders(),
      path: { attestation_id: assignment.attestation_id },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    await loadAssignments();
  }

  /**
   * Submit the structured report for an accepted Attestation.
   *
   * @param assignment - Assignment row.
   */
  async function handleSubmitReport(assignment: AttestorAssignmentResponse) {
    setError(null);
    configureBrowserClient();
    const result = await submitAttestationReport({
      body: {
        evidence_references: {},
        outcome,
        scope,
        summary,
      },
      headers: getAccessTokenHeaders(),
      path: { attestation_id: assignment.attestation_id },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    await loadAssignments();
  }

  return (
    <section className="grid gap-6">
      <HeaderCard
        eyebrow="Attestor dashboard"
        title="Assignments"
        summary="Accept cohort offers, decline work you cannot complete, and submit structured reports."
      />
      <ErrorMessage message={error} />
      <div className="grid gap-3">
        {assignments.map((assignment) => (
          <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm" key={assignment.offer_id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-heading text-lg font-bold text-foreground">
                  {formatLabel(assignment.target_type)} Attestation
                </h2>
                <p className="mt-1 text-sm text-foreground-muted">
                  Cohort {assignment.cohort_index} · due{" "}
                  {assignment.completion_due_at ?? "after acceptance"}
                </p>
              </div>
              <StatusTag value={assignment.offer_status} />
            </div>
            {assignment.offer_status === "offered" ? (
              <div className="mt-4 flex flex-wrap gap-3">
                <button className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent" onClick={() => handleOffer(assignment, "accept")} type="button">
                  Accept
                </button>
                <button className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent" onClick={() => handleOffer(assignment, "decline")} type="button">
                  Decline
                </button>
              </div>
            ) : null}
            {assignment.attestation_status === "accepted" ? (
              <div className="mt-4 grid gap-3">
                <select className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setOutcome(event.target.value as "approved" | "conditional" | "rejected")} value={outcome}>
                  <option value="approved">Approved</option>
                  <option value="conditional">Conditional</option>
                  <option value="rejected">Rejected</option>
                </select>
                <textarea className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setSummary(event.target.value)} placeholder="Report summary" value={summary} />
                <textarea className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setScope(event.target.value)} placeholder="Scope reviewed" value={scope} />
                <button className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={!canSubmitReport} onClick={() => handleSubmitReport(assignment)} type="button">
                  Submit report
                </button>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

/**
 * Render admin review and manual Attestation controls.
 */
export function AdminAttestationPanel() {
  const [applications, setApplications] = useState<AttestorApplicationResponse[]>([]);
  const [assignAttestationId, setAssignAttestationId] = useState("");
  const [assignAttestorId, setAssignAttestorId] = useState("");
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
    isNonEmpty(assignAttestorId),
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
  }, []);

  /**
   * Load pending Attestor applications for admin review.
   */
  async function loadApplications() {
    configureBrowserClient();
    const result = await listAttestorApplicationsForAdmin({
      headers: getAccessTokenHeaders(),
      query: { status: "pending" },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications(result.data.applications);
  }

  /**
   * Approve or reject an Attestor application.
   *
   * @param application - Application row.
   * @param decision - Review decision.
   */
  async function handleReview(
    application: AttestorApplicationResponse,
    decision: "approved" | "rejected",
  ) {
    setError(null);
    configureBrowserClient();
    const result = await reviewAttestorApplication({
      body: { decision, feedback: manualReason || null, totp_code: totpCode },
      headers: getAccessTokenHeaders(),
      path: { application_id: application.id },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications((current) => current.filter((item) => item.id !== application.id));
  }

  /**
   * Manually assign a needs-admin Attestation.
   */
  async function handleManualAssign() {
    setError(null);
    configureBrowserClient();
    const result = await adminAssignAttestation({
      body: {
        attestor_id: assignAttestorId,
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

  /**
   * Refund a needs-admin Attestation.
   */
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

  /**
   * Resolve an existing dispute by release, refund, or split.
   */
  async function handleResolveDispute() {
    setError(null);
    configureBrowserClient();
    const result = await resolveAttestationDispute({
      body: {
        refund_amount:
          resolutionType === "split" ? refundAmount || null : undefined,
        release_amount:
          resolutionType === "split" ? releaseAmount || null : undefined,
        resolution_notes: manualReason,
        resolution_type: resolutionType,
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
        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Admin 2FA code
            <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setTotpCode(event.target.value)} value={totpCode} />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Reason or notes
            <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setManualReason(event.target.value)} value={manualReason} />
          </label>
        </div>
      </div>
      <ApplicationList applications={applications} onReview={handleReview} />
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Needs-admin action
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setAssignAttestationId(event.target.value)} placeholder="Attestation ID" value={assignAttestationId} />
          <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setAssignAttestorId(event.target.value)} placeholder="Attestor ID" value={assignAttestorId} />
          <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setDisputeId(event.target.value)} placeholder="Dispute ID" value={disputeId} />
          <select className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setResolutionType(event.target.value as "release" | "refund" | "split")} value={resolutionType}>
            <option value="release">Release</option>
            <option value="refund">Refund</option>
            <option value="split">Split</option>
          </select>
          <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setReleaseAmount(event.target.value)} placeholder="Release amount for split" value={releaseAmount} />
          <input className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent" onChange={(event) => setRefundAmount(event.target.value)} placeholder="Refund amount for split" value={refundAmount} />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={!canAssign} onClick={handleManualAssign} type="button">
            Manual assign
          </button>
          <button className="min-h-12 rounded-xl border border-error/50 bg-error/5 px-6 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60" disabled={!canRefund} onClick={handleAdminRefund} type="button">
            Refund request
          </button>
          <button className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={!canResolveDispute} onClick={handleResolveDispute} type="button">
            Resolve dispute
          </button>
        </div>
      </div>
    </section>
  );
}

/**
 * Shared page header card for Attestation surfaces.
 */
function HeaderCard({
  eyebrow,
  summary,
  title,
}: {
  eyebrow: string;
  summary: string;
  title: string;
}) {
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        {eyebrow}
      </p>
      <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
        {title}
      </h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
        {summary}
      </p>
    </div>
  );
}

/**
 * Render one Attestation card.
 */
function AttestationCard({
  attestation,
  children,
}: {
  attestation: AttestationRequestResponse;
  children?: ReactNode;
}) {
  return (
    <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-lg font-bold text-foreground">
            {formatLabel(attestation.target_type)} · {attestation.target_id}
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Fee {formatMoney(attestation.fee_amount, attestation.currency)} ·{" "}
            {attestation.outcome ? formatLabel(attestation.outcome) : "No outcome"}
          </p>
        </div>
        <StatusTag value={attestation.status} />
      </div>
      {attestation.summary ? (
        <p className="mt-4 text-sm leading-6 text-foreground-muted">
          {attestation.summary}
        </p>
      ) : null}
      {children}
    </article>
  );
}

/**
 * Render application rows for self-service and admin contexts.
 */
function ApplicationList({
  applications,
  onReview,
  onWithdraw,
}: {
  applications: AttestorApplicationResponse[];
  onReview?: (
    application: AttestorApplicationResponse,
    decision: "approved" | "rejected",
  ) => void;
  onWithdraw?: (applicationId: string) => void;
}) {
  return (
    <div className="grid gap-3">
      {applications.length === 0 ? (
        <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
          No applications to show.
        </p>
      ) : (
        applications.map((application) => (
          <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm" key={application.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-heading text-lg font-bold text-foreground">
                  {application.specializations.join(", ")}
                </h2>
                <p className="mt-1 text-sm text-foreground-muted">
                  {application.jurisdictions.join(", ")}
                </p>
              </div>
              <StatusTag value={application.status} />
            </div>
            <p className="mt-3 text-sm leading-6 text-foreground-muted">
              {application.credentials_summary}
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              {onWithdraw && application.status === "pending" ? (
                <button className="min-h-12 rounded-xl border border-border-default px-4 text-sm font-semibold text-foreground shadow-sm outline-none transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent" onClick={() => onWithdraw(application.id)} type="button">
                  Withdraw
                </button>
              ) : null}
              {onReview ? (
                <>
                  <button className="min-h-12 rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent" onClick={() => onReview(application, "approved")} type="button">
                    Approve
                  </button>
                  <button className="min-h-12 rounded-xl border border-error px-4 text-sm font-semibold text-error shadow-sm outline-none transition-all hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error" onClick={() => onReview(application, "rejected")} type="button">
                    Reject
                  </button>
                </>
              ) : null}
            </div>
          </article>
        ))
      )}
    </div>
  );
}
