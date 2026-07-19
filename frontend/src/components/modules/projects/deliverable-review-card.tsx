"use client";

/**
 * Deliverable review card.
 *
 * Shows what the Contributor submitted for a Milestone — title, what was
 * achieved, scan status, and downloadable files — and lets the Operator approve
 * (releasing Escrow) or request changes. Downloads are presigned and only
 * offered once the virus scan marks the Deliverable visible.
 *
 * Maps to: FR-PROJ-008, FR-PROJ-009, FR-PROJ-010.
 */
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  downloadDeliverableFiles,
  listDeliverables,
} from "@/lib/generated/sdk.gen";
import type { DeliverableResponse } from "@/lib/generated/types.gen";
import { projectApi, type ProjectApiMode } from "@/lib/projects/project-api-mode";

const SCAN_LABEL: Record<string, string> = {
  pending_scan: "Scanning…",
  quarantined: "Quarantined",
  visible: "Scanned",
};

type DeliverableReviewCardProps = {
  projectId: string;
  milestoneId: string;
  /** Milestone status; changes trigger a refetch of the latest Deliverable. */
  milestoneStatus: string;
  isOperator: boolean;
  /** Refresh the workspace after an approve / revision request. */
  onChanged: () => void;
  /** Identity mode for the API call (default self). */
  mode?: ProjectApiMode;
};

/**
 * Render the latest Deliverable for a Milestone with review actions.
 */
export function DeliverableReviewCard({
  projectId,
  milestoneId,
  milestoneStatus,
  isOperator,
  onChanged,
  mode = { kind: "self" },
}: DeliverableReviewCardProps) {
  const [deliverable, setDeliverable] = useState<DeliverableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showRevision, setShowRevision] = useState(false);
  const [revisionNotes, setRevisionNotes] = useState("");

  const load = useCallback(async () => {
    configureBrowserClient();
    const result = await listDeliverables({
      headers: getAccessTokenHeaders(),
      path: { milestone_id: milestoneId, project_id: projectId },
    });
    if (result.response.ok && result.data) {
      setDeliverable(result.data.deliverables[0] ?? null);
    }
  }, [milestoneId, projectId]);

  useEffect(() => {
    void load();
  }, [load, milestoneStatus]);

  if (!deliverable) {
    return null;
  }

  const scanned = deliverable.scan_status === "visible";
  const canReview = isOperator && deliverable.status === "submitted";

  async function handleDownload() {
    if (!deliverable) {
      return;
    }
    setError(null);
    const result = await downloadDeliverableFiles({
      headers: getAccessTokenHeaders(),
      path: {
        deliverable_id: deliverable.id,
        milestone_id: milestoneId,
        project_id: projectId,
      },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    for (const file of result.data.files) {
      window.open(file.url, "_blank", "noopener,noreferrer");
    }
  }

  async function handleApprove() {
    if (!deliverable) {
      return;
    }
    setBusy(true);
    setError(null);
    const result = await projectApi(mode).approveDeliverable(
      projectId,
      milestoneId,
      deliverable.id,
    );
    setBusy(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    onChanged();
  }

  async function handleRequestRevision() {
    if (!deliverable) {
      return;
    }
    if (revisionNotes.trim().length < 5) {
      setError("Add a short note on what needs changing.");
      return;
    }
    setBusy(true);
    setError(null);
    const result = await projectApi(mode).requestDeliverableRevision(
      projectId,
      milestoneId,
      deliverable.id,
      { revision_notes: revisionNotes.trim() },
    );
    setBusy(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setShowRevision(false);
    setRevisionNotes("");
    onChanged();
  }

  return (
    <div className="mt-3 grid gap-3 rounded-xl border border-border-default bg-surface-1 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">
          Submitted: {deliverable.name}
        </p>
        <span className="rounded-md border border-border-default px-2 py-0.5 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {SCAN_LABEL[deliverable.scan_status] ?? deliverable.scan_status}
        </span>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-6 text-foreground-muted">
        {deliverable.description}
      </p>

      {scanned ? (
        <button
          className="inline-flex min-h-11 w-fit items-center rounded-xl border border-border-default px-4 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => void handleDownload()}
          type="button"
        >
          Download {deliverable.file_keys.length} file
          {deliverable.file_keys.length === 1 ? "" : "s"}
        </button>
      ) : (
        <p className="text-xs text-foreground-subtle">
          {deliverable.scan_status === "quarantined"
            ? "A file was flagged by the virus scan. Ask the contributor to re-submit."
            : "Files become downloadable once the virus scan finishes."}
        </p>
      )}

      {deliverable.status === "revision_requested" && deliverable.revision_notes ? (
        <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
          Revision requested: {deliverable.revision_notes}
        </p>
      ) : null}

      {error ? <p className="text-sm text-error">{error}</p> : null}

      {canReview ? (
        showRevision ? (
          <div className="grid gap-2">
            <textarea
              className="min-h-20 rounded-xl border border-border-default bg-surface-1 px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setRevisionNotes(event.target.value)}
              placeholder="What needs to change before you can approve?"
              value={revisionNotes}
            />
            <div className="flex flex-wrap gap-2">
              <button
                className="min-h-11 rounded-xl bg-foreground px-5 text-sm font-semibold text-background transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={busy}
                onClick={() => void handleRequestRevision()}
                type="button"
              >
                Send request
              </button>
              <button
                className="min-h-11 rounded-xl border border-border-default px-5 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                onClick={() => setShowRevision(false)}
                type="button"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button
              className="min-h-11 rounded-xl bg-[#16A34A] px-5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#16A34A]/90 focus-visible:ring-2 focus-visible:ring-[#16A34A] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busy || !scanned}
              onClick={() => void handleApprove()}
              type="button"
            >
              Approve and release escrow
            </button>
            <button
              className="min-h-11 rounded-xl border border-[#DC2626]/40 px-5 text-sm font-semibold text-[#DC2626] transition-all hover:bg-[#DC2626]/10 focus-visible:ring-2 focus-visible:ring-[#DC2626]"
              onClick={() => setShowRevision(true)}
              type="button"
            >
              Request changes
            </button>
          </div>
        )
      ) : null}
    </div>
  );
}
