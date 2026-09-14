/**
 * One status vocabulary for the admin trust console and the owner-facing
 * organization surfaces.
 *
 * Every operational status the console shows (attestor applications, KYB,
 * capabilities, calibration trials, attestations, disputes, offers,
 * invitations, membership roles, frameworks, licenses) resolves
 * through this single map, so "in review" is the same words and the same
 * colour on every screen. Requestor, attestor-org and admin attestation
 * surfaces read through `attestationStatusKey` so viewer-specific wording
 * still comes from this one map. Tones are the brand-book semantic colours via
 * tokens, never literal hexes. Unknown statuses fall back to title case in a
 * neutral tone rather than throwing.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md §4.
 */
import { formatLabel } from "@/lib/marketplace/format";

export type StatusTone = "neutral" | "info" | "warning" | "success" | "error";

export type StatusPresentation = {
  label: string;
  tone: StatusTone;
};

const PRESENTATION: Record<string, StatusPresentation> = {
  // Attestor applications
  draft: { label: "Draft", tone: "neutral" },
  submitted: { label: "Submitted", tone: "warning" },
  needs_info: { label: "Needs info", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Rejected", tone: "error" },
  // Capabilities
  active: { label: "Active", tone: "success" },
  suspended: { label: "Suspended", tone: "error" },
  revoked: { label: "Revoked", tone: "error" },
  pending: { label: "Pending", tone: "warning" },
  // Business verification (KYB)
  unverified: { label: "Not verified", tone: "neutral" },
  verified: { label: "Verified", tone: "success" },
  // A KYB rejection is not terminal (the org fixes its documents and
  // resubmits), so owner-facing surfaces present it as work to do.
  needs_changes: { label: "Needs changes", tone: "warning" },
  // A capability the org never activated (no row at all).
  inactive: { label: "Not active", tone: "neutral" },
  // Calibration trials
  assigned: { label: "Assigned", tone: "info" },
  passed: { label: "Passed", tone: "success" },
  failed: { label: "Failed", tone: "error" },
  // Attestations
  pending_fee: { label: "Awaiting payment", tone: "warning" },
  pending_owner_consent: { label: "Awaiting owner approval", tone: "warning" },
  matching: { label: "Finding attestor", tone: "info" },
  offered: { label: "Offer sent", tone: "info" },
  accepted: { label: "Accepted", tone: "info" },
  in_review: { label: "In review", tone: "warning" },
  report_submitted: { label: "Report ready", tone: "success" },
  revision_requested: { label: "Revision requested", tone: "warning" },
  released: { label: "Released", tone: "success" },
  disputed: { label: "Disputed", tone: "error" },
  resolved: { label: "Resolved", tone: "success" },
  needs_admin: { label: "Needs admin", tone: "error" },
  refunded: { label: "Refunded", tone: "neutral" },
  closed: { label: "Closed", tone: "neutral" },
  cancelled: { label: "Withdrawn", tone: "neutral" },
  // Disputes
  open: { label: "Open", tone: "warning" },
  under_review: { label: "In review", tone: "warning" },
  // Attestation, viewer-specific keys (see attestationStatusKey/offerStatusKey)
  report_sent: { label: "Submitted", tone: "info" },
  offer_open: { label: "Awaiting your response", tone: "warning" },
  // Offers
  declined: { label: "Declined", tone: "error" },
  expired: { label: "Expired", tone: "neutral" },
  superseded: { label: "Superseded", tone: "neutral" },
  // Organizations
  deactivated: { label: "Deactivated", tone: "neutral" },
  // Membership roles: neutral on purpose, a role is a fact not a state.
  owner: { label: "Owner", tone: "neutral" },
  admin: { label: "Admin", tone: "neutral" },
  member: { label: "Member", tone: "neutral" },
  // Frameworks: the pipeline is an implementation detail, so its outcomes
  // read as what they mean for the contributor's next step.
  processing: { label: "Processing", tone: "info" },
  pipeline_passed: { label: "Ready to publish", tone: "success" },
  pipeline_failed: { label: "Processing failed", tone: "error" },
  published: { label: "Published", tone: "success" },
  unpublished: { label: "Unpublished", tone: "neutral" },
};

const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "border-border-default bg-surface-2 text-foreground-muted",
  info: "border-info/30 bg-info/10 text-info",
  warning: "border-warning/30 bg-warning/10 text-warning",
  success: "border-success/30 bg-success/10 text-success",
  error: "border-error/30 bg-error/10 text-error",
};

/**
 * Map a raw status to the key the owner should read for it.
 *
 * Waiting on an administrator is always "In review" whatever the domain calls
 * it, and a resubmittable KYB rejection reads as "Needs changes".
 *
 * @param status - Raw status string from the API.
 * @param domain - Which lifecycle the status belongs to.
 */
export function ownerStatusKey(
  status: string,
  domain: "kyb" | "application" | "trial" | "capability" = "capability",
): string {
  if (status === "pending" && domain === "kyb") return "in_review";
  if (status === "submitted" && (domain === "application" || domain === "trial")) {
    return "in_review";
  }
  if (status === "rejected" && domain === "kyb") return "needs_changes";
  return status;
}

export type AttestationViewer = "requestor" | "attestor" | "admin";

/**
 * Map an attestation status to the key a given viewer should read.
 *
 * The requestor never sees the admin step: ``needs_admin`` is still "Finding
 * attestor" to them. A submitted report is "Report ready" for the requestor
 * (their action is pending) and "Submitted" for the org and admins.
 *
 * @param status - Raw attestation status from the API.
 * @param viewer - Who is looking at it.
 */
export function attestationStatusKey(status: string, viewer: AttestationViewer): string {
  if (status === "needs_admin" && viewer === "requestor") return "matching";
  if (status === "report_submitted" && viewer !== "requestor") return "report_sent";
  return status;
}

/**
 * Map an offer status to the key an attestor org should read.
 *
 * ``offered`` is the org's own pending decision, so it reads as a prompt
 * rather than the requestor-facing "Offer sent".
 *
 * @param status - Raw offer status from the API.
 */
export function offerStatusKey(status: string): string {
  return status === "offered" ? "offer_open" : status;
}

/**
 * Resolve the label and tone for a raw status value.
 *
 * @param status - Raw status string from the API.
 */
export function describeStatus(status: string): StatusPresentation {
  return PRESENTATION[status] ?? { label: formatLabel(status), tone: "neutral" };
}

type StatusPillProps = {
  /** Raw status value from the API. */
  status: string;
  /** Override the mapped label while keeping the mapped tone. */
  label?: string;
  className?: string;
};

/**
 * Render a status as a compact pill in its canonical label and tone.
 *
 * @param props - Raw status, optional label override, extra classes.
 */
export function StatusPill({ status, label, className = "" }: StatusPillProps) {
  const presentation = describeStatus(status);
  return (
    <span
      className={[
        "inline-flex items-center whitespace-nowrap rounded-badge border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em]",
        TONE_CLASSES[presentation.tone],
        className,
      ].join(" ")}
    >
      {label ?? presentation.label}
    </span>
  );
}
