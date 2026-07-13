"use client";

import { useEffect, useState } from "react";
import { CheckCircledIcon, ExclamationTriangleIcon, BorderDashedIcon } from "@radix-ui/react-icons";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { Spinner } from "@/components/ui/spinner";
import { ApplyGate } from "./apply-gate";
import { UndertakingsGate } from "./undertakings-gate";
import { TaxDocumentGate } from "./tax-document-gate";
import { TrialMemberGate } from "./trial-member-gate";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getOrgAttestorApplication } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

function StatusTag({
  status,
  label,
}: {
  status: "complete" | "needs_info" | "not_started";
  label?: string;
}) {
  if (status === "complete") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-success/10 px-2 py-0.5 text-xs font-semibold text-success">
        <CheckCircledIcon className="h-3.5 w-3.5" />
        {label ?? "Verified"}
      </span>
    );
  }
  if (status === "needs_info") {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-warning/10 px-2 py-0.5 text-xs font-semibold text-warning">
        <ExclamationTriangleIcon className="h-3.5 w-3.5" />
        {label ?? "Needs info"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded bg-surface-3 px-2 py-0.5 text-xs font-semibold text-foreground-muted">
      <BorderDashedIcon className="h-3.5 w-3.5" />
      {label ?? "Not started"}
    </span>
  );
}

function GateCard({
  title,
  description,
  status,
  statusLabel,
  feedback,
  actionText,
  children,
}: {
  title: string;
  description: string;
  status: "complete" | "needs_info" | "not_started";
  statusLabel?: string;
  feedback?: string | null;
  actionText?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h3 className="font-heading text-base font-bold text-foreground">{title}</h3>
            <StatusTag status={status} label={statusLabel} />
          </div>
          <p className="text-sm text-foreground-muted max-w-2xl">{description}</p>
          {status === "needs_info" && feedback ? (
            <div className="mt-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
              <span className="font-semibold block mb-1">Feedback from Admin:</span>
              {feedback}
            </div>
          ) : null}
        </div>
        {actionText && status !== "complete" ? (
          <button
            className="shrink-0 rounded-lg bg-foreground px-4 py-2 text-sm font-bold text-background transition hover:bg-foreground/90 disabled:opacity-50"
            disabled
            type="button"
          >
            {actionText}
          </button>
        ) : null}
      </div>
      {children && <div className="mt-4 border-t border-border-default pt-4">{children}</div>}
    </div>
  );
}

export function AttestorApplicationTab() {
  const { orgId } = useOrganization();
  const [app, setApp] = useState<OrgAttestorApplicationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

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

  if (loading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-5xl rounded-2xl border border-error/30 bg-error/10 p-6">
        <h3 className="font-bold text-error">Failed to load application</h3>
        <p className="mt-2 text-sm text-error/80">{error}</p>
      </div>
    );
  }

  const checklist = (app as { gate_checklist?: Record<string, boolean> })?.gate_checklist || {};
  
  // Compute statuses for each gate
  const applyStatus =
    app && app.status !== "draft"
      ? app.status === "needs_info"
        ? "needs_info"
        : "complete"
      : "not_started";
      
  const kybStatus = checklist?.kyb_verified ? "complete" : "not_started";
  const credentialsStatus = checklist?.credentials_reviewed ? "complete" : "not_started";

  const activationStatus = app?.status === "approved" ? "complete" : "not_started";

  return (
    <div className="mx-auto max-w-5xl space-y-6">
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
          description="Submit your organization's legal details, references, and credential summary for review."
          status={applyStatus}
          statusLabel={applyStatus === "complete" ? "Submitted" : undefined}
          feedback={applyStatus === "needs_info" ? app?.admin_feedback : undefined}
        >
          <ApplyGate application={app} orgId={orgId} onChange={reload} />
        </GateCard>
        <GateCard
          title="KYB verification"
          description="Verify your organization's legal entity and beneficial owners via Stripe."
          status={kybStatus}
        />
        <GateCard
          title="Org credentials"
          description="Admin review of your submitted credentials, licenses, and references."
          status={credentialsStatus}
          statusLabel={credentialsStatus === "complete" ? "Approved" : "Pending review"}
        />
        <GateCard
          title="Sign Undertakings"
          description="Agree to the Attestor terms of service and confidentiality obligations."
          status={app?.confidentiality_signed_at ? "complete" : "not_started"}
          statusLabel={app?.confidentiality_signed_at ? "Signed" : undefined}
        >
          <UndertakingsGate application={app} onChange={reload} />
        </GateCard>
        <GateCard
          title="Tax Documents"
          description="Provide tax documents required for payouts."
          status={app?.tax_document_key ? "complete" : "not_started"}
          statusLabel={app?.tax_document_key ? "Uploaded" : undefined}
        >
          <TaxDocumentGate application={app} onChange={reload} />
        </GateCard>
        <GateCard
          title="Trial Attestation"
          description="Complete a trial attestation to demonstrate your organization's capability."
          status={app?.gate_checklist?.trial_passed ? "complete" : app?.trial_member_id ? "needs_info" : "not_started"}
          statusLabel={
            app?.gate_checklist?.trial_passed
              ? "Passed"
              : app?.trial_member_id
                ? "Pending"
                : undefined
          }
          feedback={app?.trial_member_id ? "Trial member nominated, waiting for them to complete the trial." : undefined}
        >
          <TrialMemberGate application={app} onChange={reload} />
        </GateCard>
        <GateCard
          title="Activation"
          description="Final approval and activation of your Org Attestor status."
          status={activationStatus}
          statusLabel={activationStatus === "complete" ? "Active" : undefined}
        />
      </div>
    </div>
  );
}
