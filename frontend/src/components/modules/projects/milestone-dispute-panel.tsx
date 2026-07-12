"use client";

/**
 * Milestone dispute panel.
 *
 * Once a Milestone's Escrow is funded, a dispute is the only member-initiated
 * exit: it pauses Escrow and routes the Milestone to Admin resolution. This
 * panel shows any active or resolved dispute for the Milestone and, when none
 * is open, lets a workspace member raise one with a written reason.
 *
 * Maps to: FR-PROJ-011, FR-PROJ-012, BR-PROJ-003.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import type { DisputeResponse } from "@/lib/generated/types.gen";
import { projectApi, type ProjectApiMode } from "@/lib/projects/project-api-mode";

/** Milestone states where Escrow is held and a dispute can still be raised. */
const DISPUTABLE_MILESTONE_STATUSES = new Set([
  "funded",
  "submitted",
  "revision_requested",
]);

const MIN_REASON_LENGTH = 10;

const DISPUTE_STATUS_LABEL: Record<string, string> = {
  open: "Open",
  under_review: "Under review",
  resolved: "Resolved",
};

const RESOLUTION_LABEL: Record<string, string> = {
  release: "Released to contributor",
  refund: "Refunded to operator",
  split: "Split between parties",
};

type MilestoneDisputePanelProps = {
  projectId: string;
  milestoneId: string;
  /** Current Milestone status; gates whether a new dispute can be raised. */
  milestoneStatus: string;
  /** Active or most recent dispute for this Milestone, if any. */
  dispute: DisputeResponse | null;
  /** True when the viewer is a workspace member who may raise a dispute. */
  canRaise: boolean;
  /** Refresh the workspace after a dispute is raised. */
  onRaised: () => void;
  /** Identity mode for the API call (default self). */
  mode?: ProjectApiMode;
};

/**
 * Render dispute status and the raise-dispute control for one Milestone.
 */
export function MilestoneDisputePanel({
  projectId,
  milestoneId,
  milestoneStatus,
  dispute,
  canRaise,
  onRaised,
  mode = { kind: "self" },
}: MilestoneDisputePanelProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasActiveDispute =
    dispute !== null && dispute.status !== "resolved";
  const canOpenDispute =
    canRaise &&
    !hasActiveDispute &&
    DISPUTABLE_MILESTONE_STATUSES.has(milestoneStatus);

  async function handleSubmit() {
    if (reason.trim().length < MIN_REASON_LENGTH) {
      setError("Describe the problem in at least 10 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    const result = await projectApi(mode).createDispute(projectId, {
      milestone_id: milestoneId,
      reason: reason.trim(),
    });
    setBusy(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setOpen(false);
    setReason("");
    onRaised();
  }

  if (!dispute && !canOpenDispute) {
    return null;
  }

  return (
    <div className="mt-3 grid gap-3 rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-4">
      {dispute ? (
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[#DC2626]">Dispute</p>
            <span className="rounded-md border border-[#DC2626]/40 px-2 py-0.5 text-xs font-semibold uppercase tracking-[0.05em] text-[#DC2626]">
              {DISPUTE_STATUS_LABEL[dispute.status] ?? dispute.status}
            </span>
          </div>
          <p className="whitespace-pre-wrap text-sm leading-6 text-foreground-muted">
            {dispute.reason}
          </p>
          {dispute.status === "resolved" && dispute.resolution_type ? (
            <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
              Outcome:{" "}
              {RESOLUTION_LABEL[dispute.resolution_type] ??
                dispute.resolution_type}
              {dispute.resolution_notes ? ` — ${dispute.resolution_notes}` : ""}
            </p>
          ) : (
            <p className="text-xs text-foreground-subtle">
              Escrow is paused while an admin reviews this dispute.
            </p>
          )}
        </div>
      ) : null}

      {error ? <p className="text-sm text-[#DC2626]">{error}</p> : null}

      {canOpenDispute ? (
        open ? (
          <div className="grid gap-2">
            <textarea
              className="min-h-20 rounded-xl border border-border-default bg-surface-1 px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-[#DC2626]"
              onChange={(event) => setReason(event.target.value)}
              placeholder="Explain what went wrong. An admin will review and release, refund, or split the escrow."
              value={reason}
            />
            <div className="flex flex-wrap gap-2">
              <button
                className="min-h-11 rounded-xl bg-[#DC2626] px-5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#DC2626]/90 focus-visible:ring-2 focus-visible:ring-[#DC2626] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={busy}
                onClick={() => void handleSubmit()}
                type="button"
              >
                Submit dispute
              </button>
              <button
                className="min-h-11 rounded-xl border border-border-default px-5 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                onClick={() => {
                  setOpen(false);
                  setError(null);
                }}
                type="button"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            className="inline-flex min-h-11 w-fit items-center rounded-xl border border-[#DC2626]/40 px-4 text-sm font-semibold text-[#DC2626] transition-all hover:bg-[#DC2626]/10 focus-visible:ring-2 focus-visible:ring-[#DC2626]"
            onClick={() => setOpen(true)}
            type="button"
          >
            Raise dispute
          </button>
        )
      ) : null}
    </div>
  );
}
