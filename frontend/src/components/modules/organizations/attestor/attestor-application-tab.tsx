/**
 * Owner-facing Org Attestor application tab.
 *
 * Renders the gate checklist (apply, credentials, undertakings, tax, payout,
 * trial, activation) for the current organization, with every status drawn
 * from the shared `StatusPill` vocabulary. Owns the sticky submit bar, the
 * "start again" path after a rejection, and the activation gate's
 * suspended/revoked reason.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §2 "Attestor tab".
 */
"use client";

import { useEffect, useState } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { Spinner } from "@/components/ui/spinner";
import { Button } from "@/components/ui/button";
import { StatusPill, describeStatus } from "@/components/ui/status-pill";
import { ApplyGate } from "./apply-gate";
import { UndertakingsGate } from "./undertakings-gate";
import { PayoutAccountGate } from "./payout-account-gate";
import { TaxDocumentGate } from "./tax-document-gate";
import { TrialMemberGate } from "./trial-member-gate";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  createOrgAttestorApplication,
  getOrgAttestorApplication,
  listMyOrganizationsV1OrgsMineGet as listMyOrganizations,
  submitOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { isLengthBetween } from "@/lib/forms/validators";
import type {
  MyOrganizationResponse,
  OrgAttestorApplicationResponse,
} from "@/lib/generated/types.gen";

/**
 * Readiness for submitting the application, mirroring the backend
 * `_application_content_complete` rule so the sticky submit bar can gate the
 * action and explain what is still missing. Business verification is not part
 * of it — an organization is verified before it can open an application.
 *
 * @param app - The live application, or null before it exists.
 * @returns Whether the application can be submitted and a one-line hint.
 */
export function submissionReadiness(
  app: OrgAttestorApplicationResponse | null,
): {
  ready: boolean;
  hint: string;
} {
  if (!app) {
    return { ready: false, hint: "Save a draft to start your application." };
  }
  // Legal identity is not checked here: an org is business-verified before it
  // can apply at all, so this covers only what the application itself owns.
  const detailsComplete =
    isLengthBetween(app.credentials_summary ?? "", 10, 5000) &&
    isLengthBetween(app.professional_references ?? "", 3, 5000) &&
    (app.sectors?.length ?? 0) > 0 &&
    (app.functions?.length ?? 0) > 0 &&
    (app.jurisdictions?.length ?? 0) > 0;
  if (!detailsComplete) {
    return { ready: false, hint: "Complete the required application details." };
  }
  if (!app.payout_account_id) {
    return { ready: false, hint: "Set up a payout account to receive earnings." };
  }
  return { ready: true, hint: "Everything looks complete — send it for review." };
}

/** Vocabulary key for a gate the owner has not touched yet. */
const NOT_STARTED = "not_started";

/**
 * Vocabulary key for the Apply gate. Owners see "In review" while admins hold
 * a submitted application; every other backend status maps to itself.
 *
 * @param app - The live application, or null before it exists.
 */
export function applyGateStatus(app: OrgAttestorApplicationResponse | null): string {
  if (!app) return NOT_STARTED;
  return app.status === "submitted" ? "in_review" : app.status;
}

/**
 * Trial fields the owner response may carry beyond the gate flag. Today the
 * owner-scoped application exposes only `gate_checklist.trial_passed`; the
 * admin queue already names the decided state `trial_status`, so the same
 * name (plus `trial_feedback`) is read here when present so a failed outcome
 * and the admin's notes surface without a frontend change once exposed.
 */
type OwnerTrialFields = {
  trial_status?: string | null;
  trial_feedback?: string | null;
};

/**
 * Vocabulary key and owner-facing copy for the Trial gate.
 *
 * @param app - The live application, or null before it exists.
 * @returns The status key, an admin feedback string once decided, and a
 *   waiting note while the nominee or an admin still holds the trial.
 */
export function trialGateStatus(app: OrgAttestorApplicationResponse | null): {
  status: string;
  feedback: string | null;
  note: string | null;
} {
  if (!app?.trial_member_id) return { status: NOT_STARTED, feedback: null, note: null };
  const trial = app as OwnerTrialFields;
  const feedback = trial.trial_feedback ?? null;
  if (app.gate_checklist?.trial_passed || trial.trial_status === "passed") {
    return { status: "passed", feedback, note: null };
  }
  if (trial.trial_status === "failed") {
    return { status: "failed", feedback, note: null };
  }
  if (trial.trial_status === "submitted") {
    return {
      status: "in_review",
      feedback: null,
      note: "Trial submitted — waiting for an administrator's decision.",
    };
  }
  return {
    status: "pending",
    feedback: null,
    note: "Trial member nominated, waiting for them to complete the trial.",
  };
}

/**
 * Vocabulary key for the Activation gate. The capability map is the source of
 * truth once it exists; approval activates the capability server-side, so an
 * approved application with a stale map still reads as active.
 *
 * @param app - The live application, or null before it exists.
 * @param capability - The org's attestor capability status, if any.
 */
export function activationGateStatus(
  app: OrgAttestorApplicationResponse | null,
  capability: string | undefined,
): string {
  if (capability === "active" || capability === "suspended" || capability === "revoked") {
    return capability;
  }
  if (app?.status === "approved") return "active";
  return NOT_STARTED;
}

/**
 * One checklist row: title, shared status pill, optional admin feedback and
 * waiting note, and the gate's own controls underneath.
 *
 * @param title - Gate name.
 * @param description - One-line explanation of what the gate covers.
 * @param status - Raw vocabulary key resolved through `describeStatus`.
 * @param label - Gate-specific wording that keeps the mapped tone (e.g. "Signed").
 * @param feedback - Admin feedback to surface; tone follows the status.
 * @param note - Neutral progress note (e.g. waiting on the nominee).
 * @param children - The gate's interactive body.
 */
function GateCard({
  title,
  description,
  status,
  label,
  feedback,
  note,
  children,
}: {
  title: string;
  description: string;
  status: string;
  label?: string;
  feedback?: string | null;
  note?: string | null;
  children?: React.ReactNode;
}) {
  const tone = describeStatus(status).tone;
  const feedbackClasses =
    tone === "error"
      ? "border-error/30 bg-error/10 text-error"
      : "border-warning/30 bg-warning/10 text-warning";
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="font-heading text-base font-bold text-foreground">{title}</h3>
          <StatusPill status={status} label={label} />
        </div>
        <p className="max-w-2xl text-sm text-foreground-muted">{description}</p>
        {note ? <p className="text-sm text-foreground-muted">{note}</p> : null}
        {feedback ? (
          <div className={`mt-3 rounded-lg border p-3 text-sm ${feedbackClasses}`}>
            <span className="mb-1 block font-semibold">Feedback from Admin:</span>
            {feedback}
          </div>
        ) : null}
      </div>
      {children && <div className="mt-4 border-t border-border-default pt-4">{children}</div>}
    </div>
  );
}

/**
 * Body of the Apply gate after a rejection: explains that rejection is not
 * final and opens a fresh draft seeded from the rejected answers.
 *
 * @param application - The rejected application whose answers seed the draft.
 * @param orgId - Organization the new draft belongs to.
 * @param onStarted - Called once the draft exists so the tab reloads.
 */
function RejectedApplicationPanel({
  application,
  orgId,
  onStarted,
}: {
  application: OrgAttestorApplicationResponse;
  orgId: string;
  onStarted: () => void;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Create a new draft carrying the previous answers forward. */
  async function handleStart() {
    setStarting(true);
    setError(null);
    try {
      const res = await createOrgAttestorApplication({
        path: { org_id: orgId },
        body: {
          credentials_summary: application.credentials_summary,
          professional_references: application.professional_references,
          sample_work: application.sample_work,
          sectors: application.sectors,
          functions: application.functions,
          jurisdictions: application.jurisdictions,
        },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onStarted();
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <p className="max-w-2xl text-sm text-foreground-muted">
        This application was not approved. You can start a new one — your previous
        answers are carried over so you can revise them before resubmitting.
        {error ? <span className="mt-2 block text-error">{error}</span> : null}
      </p>
      <Button
        className="w-full sm:w-auto"
        disabled={starting}
        loading={starting}
        onClick={handleStart}
      >
        Start a new application
      </Button>
    </div>
  );
}

/**
 * Owner-facing attestor application checklist for the current organization.
 */
export function AttestorApplicationTab() {
  const { orgId, capabilities } = useOrganization();
  const [app, setApp] = useState<OrgAttestorApplicationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [capabilityReason, setCapabilityReason] = useState<string | null>(null);

  const attestorCapability = capabilities?.["attestor"];

  const reload = () => setRefreshKey((k) => k + 1);

  /** Send the application to admins for review. */
  async function handleSubmitForReview() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await submitOrgAttestorApplication({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setSubmitError(describeGeneratedError(res.error));
      } else {
        reload();
      }
    } catch {
      setSubmitError("An unexpected error occurred.");
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    let mounted = true;

    async function load() {
      configureBrowserClient();
      const res = await getOrgAttestorApplication({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) return;
      setLoading(false);
      if (res.error) {
        if (res.response?.status === 404) {
          // No application exists yet; we render the default unstarted gates.
          setApp(null);
        } else {
          setError(describeGeneratedError(res.error));
        }
      } else {
        setApp(res.data);
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [orgId, refreshKey]);

  // The org context carries capability statuses but not the admin's reason,
  // which only /v1/orgs/mine returns; fetch it just for the two states that
  // have one so the Activation gate can explain itself.
  useEffect(() => {
    if (attestorCapability !== "suspended" && attestorCapability !== "revoked") {
      setCapabilityReason(null);
      return;
    }
    let mounted = true;
    async function loadReason() {
      const res = await listMyOrganizations({ headers: getAccessTokenHeaders() });
      if (!mounted || res.error || !res.data) return;
      const mine = res.data.organizations.find(
        (entry: MyOrganizationResponse) => entry.org.id === orgId,
      );
      setCapabilityReason(mine?.capability_reasons?.["attestor"] ?? null);
    }
    void loadReason();
    return () => {
      mounted = false;
    };
  }, [orgId, attestorCapability, refreshKey]);

  if (loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-5xl rounded-2xl border border-error/30 bg-error/10 p-6">
        <h3 className="font-bold text-error">Failed to load application</h3>
        <p className="mt-2 text-sm text-error/80">{error}</p>
      </div>
    );
  }

  const applyStatus = applyGateStatus(app);
  const credentialsStatus = app?.gate_checklist?.credentials_reviewed
    ? "approved"
    : applyStatus === "in_review"
      ? "in_review"
      : NOT_STARTED;
  const trial = trialGateStatus(app);
  const activationStatus = activationGateStatus(app, attestorCapability);
  const isRejected = app?.status === "rejected";

  // Only draft and needs-info applications can be (re)submitted for review;
  // a rejected one starts over through the Apply gate instead.
  const editable =
    !!app && (app.status === "draft" || app.status === "needs_info");
  const readiness = submissionReadiness(app);

  return (
    <div className="max-w-5xl space-y-6">
      <header>
        <h2 className="font-heading text-2xl font-extrabold text-foreground">
          Attestor Application
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Complete the following checklist to become a verified Org Attestor on
          Auracles. Start with <span className="font-semibold text-foreground">Apply</span>{" "}
          below.
        </p>
      </header>

      <div className="space-y-4">
        <GateCard
          title="Apply"
          description="Submit your organization's references and credential summary for review."
          status={applyStatus}
          feedback={
            applyStatus === "needs_info" || isRejected ? app?.admin_feedback : undefined
          }
        >
          {app && isRejected ? (
            <RejectedApplicationPanel application={app} orgId={orgId} onStarted={reload} />
          ) : (
            <ApplyGate application={app} orgId={orgId} onChange={reload} />
          )}
        </GateCard>
        <GateCard
          title="Org credentials"
          description="Admin review of your submitted credentials, licenses, and references."
          status={credentialsStatus}
        />
        <GateCard
          title="Sign Undertakings"
          description="Agree to the Attestor terms of service and confidentiality obligations."
          status={app?.confidentiality_signed_at ? "approved" : NOT_STARTED}
          label={app?.confidentiality_signed_at ? "Signed" : undefined}
        >
          <UndertakingsGate application={app} onChange={reload} />
        </GateCard>
        <GateCard
          title="Tax Documents"
          description="Provide tax documents required for payouts."
          status={app?.tax_document_key ? "approved" : NOT_STARTED}
          label={app?.tax_document_key ? "Uploaded" : undefined}
        >
          <TaxDocumentGate application={app} onChange={reload} />
        </GateCard>
        <GateCard
          title="Payout Account"
          description="Connect an org-owned payout destination so you can receive attestation earnings."
          status={app?.payout_account_id ? "approved" : NOT_STARTED}
          label={app?.payout_account_id ? "Linked" : undefined}
        >
          <PayoutAccountGate application={app} orgId={orgId} onChange={reload} />
        </GateCard>
        <GateCard
          title="Trial Attestation"
          description="Complete a trial attestation to demonstrate your organization's capability."
          status={trial.status}
          feedback={trial.feedback}
          note={trial.note}
        >
          <TrialMemberGate application={app} onChange={reload} />
        </GateCard>
        <GateCard
          title="Activation"
          description="Final approval and activation of your Org Attestor status."
          status={activationStatus}
        >
          {activationStatus === "suspended" || activationStatus === "revoked" ? (
            <div className="space-y-1 text-sm text-foreground">
              <p>
                <span className="font-semibold">Reason:</span>{" "}
                {capabilityReason ?? "No reason was recorded."}
              </p>
              {activationStatus === "revoked" ? (
                <p className="text-foreground-muted">Contact support to appeal.</p>
              ) : null}
            </div>
          ) : null}
        </GateCard>
      </div>

      {editable && (
        <div className="sticky bottom-0 z-10 rounded-xl border border-border-default bg-surface-1/95 p-4 shadow-lg backdrop-blur">
          {submitError && (
            <p className="mb-2 text-sm text-error">{submitError}</p>
          )}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-foreground-muted">{readiness.hint}</p>
            <Button
              className="w-full sm:w-auto"
              disabled={!readiness.ready || submitting}
              loading={submitting}
              onClick={handleSubmitForReview}
            >
              {app?.status === "needs_info" ? "Resubmit for review" : "Submit for review"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
