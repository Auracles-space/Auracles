/**
 * One status vocabulary for the admin trust console.
 *
 * Every operational status the console shows (attestor applications, KYB,
 * capabilities, calibration trials, attestations, disputes, offers) resolves
 * through this single map, so "in review" is the same words and the same
 * colour on every screen. Tones are the brand-book semantic colours via
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
  // Offers
  declined: { label: "Declined", tone: "error" },
  expired: { label: "Expired", tone: "neutral" },
  superseded: { label: "Superseded", tone: "neutral" },
  // Organizations
  deactivated: { label: "Deactivated", tone: "neutral" },
};

const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "border-border-default bg-surface-2 text-foreground-muted",
  info: "border-info/30 bg-info/10 text-info",
  warning: "border-warning/30 bg-warning/10 text-warning",
  success: "border-success/30 bg-success/10 text-success",
  error: "border-error/30 bg-error/10 text-error",
};

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
