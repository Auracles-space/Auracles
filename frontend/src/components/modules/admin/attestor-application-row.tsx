"use client";

/**
 * One attestor-application card in the admin review list.
 *
 * Self-contained: carries its own rejection-feedback field and Reject action so
 * the admin never scrolls to a shared form. Rejecting an application only needs
 * feedback (no 2FA); on success the card drops itself from the list.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { rejectOrgAttestor } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { Input } from "@/components/ui/input";
import { StatusTag } from "@/components/modules/attestation/attestation-status";

type AttestorApplicationRowProps = {
  /** The application being reviewed. */
  application: OrgAttestorApplicationResponse;
  /** Called with the application id once it is rejected. */
  onRejected: (applicationId: string) => void;
};

/**
 * Render one attestor application with inline reject controls.
 *
 * @param props - The application and the rejection callback.
 */
export function AttestorApplicationRow({
  application,
  onRejected,
}: AttestorApplicationRowProps) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPending =
    application.status !== "active" && application.status !== "rejected";
  const canReject = feedback.trim().length > 0 && !busy;

  /** Terminally reject this application with the entered feedback. */
  async function handleReject() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await rejectOrgAttestor({
        body: { feedback },
        headers: getAccessTokenHeaders(),
        path: { application_id: application.id },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      onRejected(application.id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
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

      {isPending ? (
        <div className="mt-4 grid gap-3">
          <label className="grid gap-2 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
            Rejection feedback
            <Input
              onChange={(event) => setFeedback(event.target.value)}
              placeholder="Why is this application rejected?"
              value={feedback}
            />
          </label>
          {error ? <p className="text-sm text-error">{error}</p> : null}
          <div className="flex flex-wrap gap-3">
            <button
              className="min-h-12 rounded-xl border border-error px-5 text-sm font-semibold text-error shadow-sm outline-none transition-all hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canReject}
              onClick={handleReject}
              type="button"
            >
              Reject
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}
