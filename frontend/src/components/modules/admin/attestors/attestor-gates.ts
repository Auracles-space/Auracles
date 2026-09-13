/**
 * Pure gate logic for the attestor application pipeline.
 *
 * Gates run in sequence: business verification (settled on the organization)
 * → calibration trial → approval. Only the next undone step is live; the
 * console renders whatever this function says rather than re-deriving it per
 * button, so the rules live in one testable place.
 */
import type { OrgAttestorAdminListItem } from "@/lib/generated/types.gen";

export type CapabilityTransitions = {
  canSuspend: boolean;
  canReinstate: boolean;
  canRevoke: boolean;
};

export type ApplicationGates = {
  /** Application is neither approved nor rejected. */
  underReview: boolean;
  /** Application reached a terminal decision. */
  decided: boolean;
  kybDone: boolean;
  trialPassed: boolean;
  trialSubmitted: boolean;
  awaitingNominee: boolean;
  canStartTrial: boolean;
  canApprove: boolean;
  canNeedsInfo: boolean;
  canReject: boolean;
  /** One sentence naming the next action, or null when nothing is pending. */
  nextStep: string | null;
  capability: CapabilityTransitions;
};

/**
 * Derive every gate and allowed action for one application row.
 *
 * @param app - The application as listed for admins.
 */
export function computeGates(app: OrgAttestorAdminListItem): ApplicationGates {
  const decided = app.status === "approved" || app.status === "rejected";
  const underReview = app.status === "submitted" || app.status === "needs_info";
  const kybDone = app.kyb_status === "verified";
  const trialPassed = app.trial_status === "passed";
  const trialSubmitted = app.trial_status === "submitted";
  const awaitingNominee = app.trial_status === "assigned";
  const trialFailed = app.trial_status === "failed";

  const canStartTrial =
    underReview && kybDone && !trialPassed && !awaitingNominee && !trialSubmitted;
  const canApprove = app.status === "submitted" && kybDone && trialPassed;
  const canNeedsInfo = app.status === "submitted";
  const canReject = !decided;

  let nextStep: string | null = null;
  if (app.status === "needs_info") {
    nextStep = "Waiting on the organization to resubmit.";
  } else if (underReview) {
    if (!kybDone) {
      nextStep = "Verify the organization first.";
    } else if (awaitingNominee) {
      nextStep = "Waiting on the nominee to complete the trial.";
    } else if (trialSubmitted) {
      nextStep = "Grade the submitted trial.";
    } else if (trialFailed) {
      nextStep = "Trial failed. Start it again for another attempt.";
    } else if (!trialPassed) {
      nextStep = "Start the calibration trial.";
    } else {
      nextStep = "All gates met. Ready to approve.";
    }
  }

  const capabilityStatus = app.capability_status ?? null;
  const capability: CapabilityTransitions = {
    canSuspend: capabilityStatus === "active",
    canReinstate: capabilityStatus === "suspended",
    canRevoke: capabilityStatus === "active" || capabilityStatus === "suspended",
  };

  return {
    underReview,
    decided,
    kybDone,
    trialPassed,
    trialSubmitted,
    awaitingNominee,
    canStartTrial,
    canApprove,
    canNeedsInfo,
    canReject,
    nextStep,
    capability,
  };
}
