/**
 * Step and review-stage logic for the owner's attestor application.
 *
 * The owner completes five steps and submits. Everything after submission
 * (admin review, calibration trial, approval, activation) is admin-driven, so
 * it is read as one review stage shown above the steps rather than as steps
 * the owner could appear to act on.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §2 "Attestor tab".
 */
import { isLengthBetween } from "@/lib/forms/validators";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

type Application = OrgAttestorApplicationResponse | null;

/** Identifier of one owner step. */
export type StepId = "details" | "undertakings" | "tax" | "payout" | "trial_member" | "submit";

/** One owner step: short stepper label plus the panel title and description. */
export type ApplicationStep = {
  id: StepId;
  label: string;
  title: string;
  description: string;
};

/** The owner's steps, in order. */
export const APPLICATION_STEPS: readonly ApplicationStep[] = [
  {
    id: "details",
    label: "Details",
    title: "Application details",
    description:
      "Your credentials summary and references, and the sectors, functions, and jurisdictions you can attest.",
  },
  {
    id: "undertakings",
    label: "Undertakings",
    title: "Sign undertakings",
    description: "Declare conflicts of interest and agree to the confidentiality undertaking.",
  },
  {
    id: "tax",
    label: "Tax document",
    title: "Upload the tax document",
    description: "Required before attestation earnings can be paid out.",
  },
  {
    id: "payout",
    label: "Payout account",
    title: "Connect a payout account",
    description: "The organization's bank account for attestation earnings.",
  },
  {
    id: "trial_member",
    label: "Trial member",
    title: "Nominate the trial member",
    description:
      "The NDA-signed member who completes the calibration trial once an administrator starts it.",
  },
  {
    id: "submit",
    label: "Submit",
    title: "Review and submit",
    description: "Check every step, then send the application to an administrator.",
  },
];

/** The five steps the owner completes before submitting. */
export const OWNER_STEPS = APPLICATION_STEPS.filter((step) => step.id !== "submit");

/**
 * Whether the application is still in the owner's hands.
 *
 * @param app - The live application, or null before it exists.
 */
export function isEditable(app: Application): boolean {
  return !app || app.status === "draft" || app.status === "needs_info";
}

/**
 * Whether one step is complete, mirroring the backend content and approval gates.
 *
 * @param app - The live application, or null before it exists.
 * @param id - Step to check.
 */
export function stepComplete(app: Application, id: StepId): boolean {
  if (!app) return false;
  switch (id) {
    case "details":
      return (
        isLengthBetween(app.credentials_summary ?? "", 10, 5000) &&
        isLengthBetween(app.professional_references ?? "", 3, 5000) &&
        (app.sectors?.length ?? 0) > 0 &&
        (app.functions?.length ?? 0) > 0 &&
        (app.jurisdictions?.length ?? 0) > 0
      );
    case "undertakings":
      return Boolean(app.coi_signed_at && app.confidentiality_signed_at);
    case "tax":
      return Boolean(app.tax_document_key);
    case "payout":
      return Boolean(app.payout_account_id);
    case "trial_member":
      return Boolean(app.trial_member_id);
    case "submit":
      return !isEditable(app);
  }
}

/**
 * The step to open on: the first incomplete owner step, else Submit.
 *
 * @param app - The live application, or null before it exists.
 */
export function initialStep(app: Application): StepId {
  return OWNER_STEPS.find((step) => !stepComplete(app, step.id))?.id ?? "submit";
}

/**
 * Whether the application can be submitted, and what is still missing.
 *
 * The server only requires the details, but an administrator cannot start the
 * trial without a nominee or approve without the undertakings, tax document,
 * and payout account, so submitting earlier would stall in review.
 *
 * @param app - The live application, or null before it exists.
 */
export function submissionReadiness(app: Application): { ready: boolean; hint: string } {
  if (!app) {
    return { ready: false, hint: "Save a draft to start your application." };
  }
  if (!stepComplete(app, "details")) {
    return { ready: false, hint: "Complete the required application details." };
  }
  const missing = OWNER_STEPS.filter((step) => !stepComplete(app, step.id));
  if (missing.length > 0) {
    return {
      ready: false,
      hint: `Finish these steps first: ${missing.map((step) => step.label).join(", ")}.`,
    };
  }
  return { ready: true, hint: "Everything is complete. Send it for review." };
}

/** Where the application stands, for the banner above the steps. */
export type ReviewStage = {
  status: string;
  label?: string;
  title: string;
  detail: string;
  feedback?: string | null;
};

/** Trial fields the owner response may carry. */
type TrialFields = { trial_status?: string | null; trial_feedback?: string | null };

/**
 * Describe the application's current stage.
 *
 * @param app - The live application, or null before it exists.
 * @param capability - The org's attestor capability status, if any.
 */
export function reviewStage(app: Application, capability: string | undefined): ReviewStage {
  if (capability === "suspended" || capability === "revoked") {
    return {
      status: capability,
      title: capability === "suspended" ? "Attestor status suspended" : "Attestor status revoked",
      detail: "Your organization cannot take attestation work while this applies.",
    };
  }
  if (capability === "active" || app?.status === "approved") {
    return {
      status: "active",
      title: "Your organization is an active attestor",
      detail: "Attestation offers arrive on the Offers tab; assigned reviews appear on the Queue tab.",
    };
  }
  if (!app) {
    return {
      status: "not_started",
      label: "Not started",
      title: "Apply to become an attestor organization",
      detail:
        "Complete the steps below and submit. An administrator reviews the application and runs a calibration trial before approval.",
    };
  }
  if (app.status === "rejected") {
    return {
      status: "rejected",
      title: "Application not approved",
      detail: "You can start a new application; your previous answers carry over.",
      feedback: app.admin_feedback,
    };
  }
  if (app.status === "needs_info") {
    return {
      status: "needs_info",
      title: "Changes requested",
      detail: "Update the steps below, then resubmit.",
      feedback: app.admin_feedback,
    };
  }
  if (app.status === "draft") {
    const done = OWNER_STEPS.filter((step) => stepComplete(app, step.id)).length;
    return {
      status: "draft",
      title: "Draft application",
      detail: `${done} of ${OWNER_STEPS.length} steps complete. Submit once every step is done.`,
    };
  }
  const trial = app as TrialFields;
  switch (trial.trial_status) {
    case "assigned":
      return {
        status: "pending",
        title: "Calibration trial in progress",
        detail: "Trial member nominated, waiting for them to complete the trial.",
      };
    case "submitted":
      return {
        status: "in_review",
        title: "Trial awaiting grading",
        detail: "The trial is submitted. An administrator is grading it.",
      };
    case "passed":
      return {
        status: "passed",
        title: "Calibration trial passed",
        detail: "Waiting for an administrator's final approval.",
        feedback: trial.trial_feedback,
      };
    case "failed":
      return {
        status: "failed",
        title: "Calibration trial not passed",
        detail: "An administrator can start another attempt.",
        feedback: trial.trial_feedback,
      };
    default:
      return {
        status: "in_review",
        title: "Application in review",
        detail: "An administrator is reviewing your application and will start the calibration trial.",
      };
  }
}

/** Labels of the review track shown in the banner. */
export const REVIEW_TRACK = ["Submit", "Review and trial", "Approval", "Activation"] as const;

/**
 * Index into `REVIEW_TRACK` of the current stage.
 *
 * @param app - The live application, or null before it exists.
 * @param capability - The org's attestor capability status, if any.
 */
export function stageIndex(app: Application, capability: string | undefined): number {
  if (capability === "active" || capability === "suspended" || capability === "revoked") return 3;
  if (!app || isEditable(app)) return 0;
  if (app.status === "approved") return 3;
  return (app as TrialFields).trial_status === "passed" ? 2 : 1;
}
