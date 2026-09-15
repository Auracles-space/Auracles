/**
 * Owner-facing Org Attestor application tab.
 *
 * A review-stage banner pinned on top says where the application stands and
 * what happens next; below it, a horizontal stepper walks the owner through
 * their five steps and the submission, with free Back/Next navigation. Stages
 * after submission (review, calibration trial, approval, activation) are
 * admin-driven and live only in the banner.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §2 "Attestor tab".
 */
"use client";

import { useEffect, useState, type ReactNode } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getOrgAttestorApplication,
  listMyOrganizationsV1OrgsMineGet as listMyOrganizations,
  submitOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type {
  MyOrganizationResponse,
  OrgAttestorApplicationResponse,
} from "@/lib/generated/types.gen";

import { ApplyGate } from "./apply-gate";
import { ApplicationStatusBanner } from "./application-status-banner";
import { ApplicationSubmitPanel } from "./application-submit-panel";
import { ApplicationStepper } from "./application-stepper";
import {
  APPLICATION_STEPS,
  initialStep,
  reviewStage,
  stageIndex,
  stepComplete,
  type StepId,
} from "./application-steps";
import { PayoutAccountGate } from "./payout-account-gate";
import { RejectedApplicationPanel } from "./rejected-application-panel";
import { TaxDocumentGate } from "./tax-document-gate";
import { TrialMemberGate } from "./trial-member-gate";
import { UndertakingsGate } from "./undertakings-gate";

/**
 * Owner-facing attestor application: stage banner plus step-by-step form.
 */
export function AttestorApplicationTab() {
  const { orgId, capabilities } = useOrganization();
  const [app, setApp] = useState<OrgAttestorApplicationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeStep, setActiveStep] = useState<StepId | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [capabilityReason, setCapabilityReason] = useState<string | null>(null);

  const attestorCapability = capabilities?.["attestor"];
  const reload = () => setRefreshKey((k) => k + 1);

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
          // No application yet: the steps start empty.
          setApp(null);
          setActiveStep((current) => current ?? "details");
        } else {
          setError(describeGeneratedError(res.error));
        }
        return;
      }
      setApp(res.data);
      // Open on the first incomplete step once; later reloads keep the
      // owner where they are.
      setActiveStep((current) => current ?? initialStep(res.data));
    }
    void load();
    return () => {
      mounted = false;
    };
  }, [orgId, refreshKey]);

  // The org context carries capability statuses but not the admin's reason,
  // which only /v1/orgs/mine returns; fetch it just for the two states that
  // have one.
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

  /** Send the application to administrators for review. */
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

  const stage = reviewStage(app, attestorCapability);
  const isRejected = app?.status === "rejected" && !attestorCapability;
  const stepId = activeStep ?? initialStep(app);
  const stepIndex = APPLICATION_STEPS.findIndex((step) => step.id === stepId);
  const step = APPLICATION_STEPS[stepIndex];

  const panels: Record<StepId, ReactNode> = {
    details: <ApplyGate application={app} onChange={reload} orgId={orgId} />,
    undertakings: <UndertakingsGate application={app} onChange={reload} />,
    tax: <TaxDocumentGate application={app} onChange={reload} />,
    payout: <PayoutAccountGate application={app} onChange={reload} orgId={orgId} />,
    trial_member: <TrialMemberGate application={app} onChange={reload} />,
    submit: (
      <ApplicationSubmitPanel
        application={app}
        error={submitError}
        onGoTo={setActiveStep}
        onSubmit={handleSubmitForReview}
        submitting={submitting}
      />
    ),
  };

  return (
    <div className="max-w-5xl space-y-6">
      <header>
        <h2 className="font-heading text-2xl font-extrabold text-foreground">
          Attestor application
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Become a verified attestor organization on Auracles.
        </p>
      </header>

      <ApplicationStatusBanner
        capability={attestorCapability}
        capabilityReason={capabilityReason}
        stage={stage}
        trackIndex={isRejected ? null : stageIndex(app, attestorCapability)}
      >
        {isRejected && app ? (
          <RejectedApplicationPanel application={app} onStarted={reload} orgId={orgId} />
        ) : null}
      </ApplicationStatusBanner>

      {isRejected ? null : (
        <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm sm:p-6">
          <ApplicationStepper
            activeId={stepId}
            isComplete={(id) => stepComplete(app, id)}
            onSelect={setActiveStep}
            steps={APPLICATION_STEPS}
          />

          <div className="mt-6 rounded-xl border border-border-default bg-surface-2 p-4 sm:p-5">
            <h3 className="font-heading text-lg font-bold text-foreground">{step.title}</h3>
            <p className="mt-1 max-w-2xl text-sm text-foreground-muted">{step.description}</p>
            <div className="mt-4 border-t border-border-default pt-4">{panels[stepId]}</div>
          </div>

          <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
            <Button
              disabled={stepIndex === 0}
              onClick={() => setActiveStep(APPLICATION_STEPS[stepIndex - 1].id)}
              variant="secondary"
            >
              Back
            </Button>
            {stepIndex < APPLICATION_STEPS.length - 1 ? (
              <Button onClick={() => setActiveStep(APPLICATION_STEPS[stepIndex + 1].id)} variant="secondary">
                Next
              </Button>
            ) : null}
          </div>
        </section>
      )}
    </div>
  );
}
