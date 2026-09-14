/**
 * Ordered progress track for one Attestation request.
 *
 * A requestor reads a single status word and cannot tell how far through the
 * six-stage lifecycle their request is, or what is still ahead. This renders
 * the whole track — Requested, Paid, Attestor assigned, In review, Report,
 * Closed — with the reached stages marked, so the position is legible at a
 * glance. Vertical on phones, horizontal from `md:` up.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";

export type ProgressState = "done" | "current" | "upcoming";

export type ProgressStep = {
  /** Human label for the stage. */
  label: string;
  /** Whether the request has passed, is sitting on, or has yet to reach it. */
  state: ProgressState;
};

const STEP_LABELS = [
  "Requested",
  "Paid",
  "Attestor assigned",
  "In review",
  "Report",
  "Closed",
];

/** Index of the stage each status sits on. */
const STATUS_STEP: Record<string, number> = {
  pending_owner_consent: 0,
  pending_fee: 1,
  matching: 2,
  needs_admin: 2,
  offered: 2,
  accepted: 3,
  in_review: 3,
  revision_requested: 3,
  report_submitted: 4,
  disputed: 4,
  // Past the last stage: a released request has nothing left to do, so every
  // stage including "Closed" reads as done.
  released: 6,
  closed: 6,
};

/** Statuses that end the request without reaching a normal close. */
const ENDED_STATUSES = ["cancelled", "refunded"];

/**
 * Resolve the six lifecycle stages and their state for one Attestation.
 *
 * A request that ended early (withdrawn or refunded) cannot be placed on the
 * track by status alone, so its earlier stages are marked from the evidence on
 * the record — an escrow means it was paid, an attestor org means it was
 * assigned — and the final stage reads "Ended" rather than "Closed".
 *
 * @param attestation - The attestation as returned to its requestor.
 * @returns The stages in order, each with its state.
 */
export function attestationProgressSteps(
  attestation: AttestationRequestResponse,
): ProgressStep[] {
  if (ENDED_STATUSES.includes(attestation.status)) {
    const reached = [
      true,
      Boolean(attestation.escrow_id),
      Boolean(attestation.attestor_org_id),
      Boolean(attestation.accepted_at),
      Boolean(attestation.report_key || attestation.summary),
    ];
    return STEP_LABELS.map((label, index) =>
      index === 5
        ? { label: "Ended", state: "current" as ProgressState }
        : {
            label,
            state: (reached[index] ? "done" : "upcoming") as ProgressState,
          },
    );
  }

  const current = STATUS_STEP[attestation.status] ?? 0;
  return STEP_LABELS.map((label, index) => ({
    label,
    state:
      index < current ? "done" : index === current ? "current" : "upcoming",
  }));
}

const MARKER_CLASSES: Record<ProgressState, string> = {
  done: "border-success bg-success/20 text-success",
  current: "border-accent bg-accent/15 text-accent",
  upcoming: "border-border-default bg-surface-2 text-foreground-muted",
};

const LABEL_CLASSES: Record<ProgressState, string> = {
  done: "text-foreground",
  current: "font-semibold text-foreground",
  upcoming: "text-foreground-muted",
};

/**
 * Render the Attestation progress track.
 *
 * @param props - The attestation whose progress is shown.
 */
export function AttestationProgress({
  attestation,
}: {
  attestation: AttestationRequestResponse;
}) {
  const steps = attestationProgressSteps(attestation);
  return (
    <ol
      aria-label="Request progress"
      className="grid gap-3 md:grid-cols-6 md:gap-2"
    >
      {steps.map((step) => (
        <li
          aria-current={step.state === "current" ? "step" : undefined}
          className="flex items-center gap-3 md:flex-col md:items-start md:gap-2"
          key={step.label}
        >
          <span
            aria-hidden="true"
            className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full border text-[11px] font-bold md:h-2.5 md:w-full md:rounded-full ${MARKER_CLASSES[step.state]}`}
          >
            <span className="md:hidden">{step.state === "done" ? "✓" : ""}</span>
          </span>
          <span className={`text-sm md:text-xs ${LABEL_CLASSES[step.state]}`}>
            {step.label}
          </span>
        </li>
      ))}
    </ol>
  );
}
