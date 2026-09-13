"use client";

/**
 * One attestor application in the admin pipeline.
 *
 * Collapsed: organization, status pills for every gate, created date, and
 * the next step in one line. Expanded: review documents, the feedback last
 * sent, the gated decision controls, the trial grader when a trial is
 * awaiting a decision, and capability controls once approved. State changes
 * are applied locally through `onUpdate` so the pipeline advances without a
 * refetch.
 */
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { useState } from "react";

import { StatusPill } from "@/components/ui/status-pill";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  approveOrgAttestor,
  orgAttestorNeedsInfo,
  rejectOrgAttestor,
  startOrgAttestorTrial,
} from "@/lib/generated/sdk.gen";
import type {
  CalibrationFixtureItem,
  OrgAttestorAdminListItem,
} from "@/lib/generated/types.gen";

import { AttestorApplicationActions } from "./attestor-application-actions";
import { AttestorCapabilityControls } from "./attestor-capability-controls";
import { AttestorDocuments } from "./attestor-documents";
import { computeGates } from "./attestor-gates";
import { AttestorTrialGrader } from "./attestor-trial-grader";

type AttestorApplicationCardProps = {
  app: OrgAttestorAdminListItem;
  fixtures: CalibrationFixtureItem[];
  defaultOpen?: boolean;
  onUpdate: (applicationId: string, patch: Partial<OrgAttestorAdminListItem>) => void;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
};

/**
 * Render one application row with its expandable review workspace.
 *
 * @param props - The application, fixtures for the trial picker, callbacks.
 */
export function AttestorApplicationCard({
  app,
  fixtures,
  defaultOpen = false,
  onUpdate,
  onNotice,
  onError,
}: AttestorApplicationCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState(false);
  const gates = computeGates(app);
  const orgName = app.org_name || "Unnamed organization";

  async function run<T extends { status?: string }>(
    call: () => Promise<{ response: Response; data?: T; error?: unknown }>,
    patch: Partial<OrgAttestorAdminListItem>,
    notice: string,
  ) {
    setBusy(true);
    configureBrowserClient();
    try {
      const result = await call();
      if (!result.response.ok || !result.data) {
        onError(describeGeneratedError(result.error));
        return;
      }
      onUpdate(app.id, {
        ...(result.data.status ? { status: result.data.status } : {}),
        ...patch,
      });
      onNotice(notice);
    } catch {
      onError("The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  const headers = () => getAccessTokenHeaders();
  const path = { application_id: app.id };

  return (
    <article className="rounded-2xl border border-border-default bg-surface-1 shadow-sm">
      <button
        aria-expanded={open}
        className="grid w-full gap-3 rounded-2xl p-5 text-left outline-none transition-colors hover:bg-surface-2/60 focus-visible:ring-2 focus-visible:ring-accent sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-heading text-lg font-bold text-foreground">{orgName}</h3>
            <StatusPill status={app.status} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusPill
              label={gates.kybDone ? "Verified" : "Not verified"}
              status={app.kyb_status ?? "unverified"}
            />
            <StatusPill
              label={app.trial_status ? `Trial ${app.trial_status}` : "No trial"}
              status={app.trial_status ?? "draft"}
            />
            {app.capability_status ? (
              <StatusPill
                label={`Capability ${app.capability_status}`}
                status={app.capability_status}
              />
            ) : null}
          </div>
          <p className="mt-2 text-sm text-foreground-muted">
            Applied {new Date(app.created_at).toLocaleDateString()}
            {gates.nextStep ? ` · ${gates.nextStep}` : ""}
          </p>
        </div>
        <ChevronDownIcon
          aria-hidden="true"
          className={`h-5 w-5 shrink-0 text-foreground-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open ? (
        <div className="grid gap-4 border-t border-border-default p-5">
          {app.admin_feedback ? (
            <p className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-foreground">
              <span className="font-semibold">Last feedback sent:</span> {app.admin_feedback}
            </p>
          ) : null}

          <AttestorDocuments applicationId={app.id} />

          {gates.trialSubmitted ? (
            <AttestorTrialGrader
              applicationId={app.id}
              onDecided={(result, status) => {
                onUpdate(app.id, {
                  status,
                  trial_status: result === "pass" ? "passed" : "failed",
                });
                onNotice(result === "pass" ? "Trial marked as passed." : "Trial marked as failed.");
              }}
              onError={onError}
            />
          ) : null}

          <AttestorApplicationActions
            busy={busy}
            fixtures={fixtures}
            gates={gates}
            onApprove={() =>
              void run(
                () => approveOrgAttestor({ headers: headers(), path }),
                { capability_status: "active" },
                "Application approved. Attestor capability is active.",
              )
            }
            onNeedsInfo={(feedback) =>
              void run(
                () => orgAttestorNeedsInfo({ headers: headers(), path, body: { feedback } }),
                { admin_feedback: feedback },
                "Sent back to the organization for more information.",
              )
            }
            onReject={(feedback) =>
              void run(
                () => rejectOrgAttestor({ headers: headers(), path, body: { feedback } }),
                { admin_feedback: feedback },
                "Application rejected.",
              )
            }
            onStartTrial={(fixtureId) =>
              void run(
                () =>
                  startOrgAttestorTrial({
                    headers: headers(),
                    path,
                    body: { framework_id: fixtureId },
                  }),
                { trial_status: "assigned" },
                "Trial assigned to the nominated member.",
              )
            }
            orgName={orgName}
          />

          {app.status === "approved" ? (
            <AttestorCapabilityControls
              onChanged={(status) => {
                onUpdate(app.id, { capability_status: status });
                onNotice(`Attestor capability is now ${status}.`);
              }}
              onError={onError}
              orgId={app.org_id}
              orgName={orgName}
              transitions={gates.capability}
            />
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
