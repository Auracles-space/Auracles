/**
 * Credential verification status badge.
 *
 * Maps a Credential's `verification_status` to a brand-book semantic colour
 * pill, mirroring the {@link StatusBadge} idiom (low-opacity background,
 * full-opacity text, uppercase tracking, `rounded-badge`). When a verified
 * credential has lapsed, an additional neutral "Expired" pill is rendered so
 * the trust signal degrades gracefully.
 *
 * Maps to: FR-ATT credential verification lifecycle.
 */

/** Variant token bundle for one verification status. */
type StatusVariant = {
  classes: string;
  label: string;
};

/**
 * Resolve the label + Tailwind token bundle for a verification status.
 *
 * Unknown statuses fall back to the muted "Not submitted" variant so the badge
 * never renders an empty/unstyled pill.
 *
 * @param status - Raw `verification_status` from the credential record.
 */
function resolveVariant(status: string): StatusVariant {
  switch (status) {
    case "verified":
      return {
        classes: "border-success/30 bg-success/10 text-success",
        label: "Verified",
      };
    case "pending":
      return {
        classes: "border-warning/30 bg-warning/10 text-warning",
        label: "Pending review",
      };
    case "rejected":
      return {
        classes: "border-error/30 bg-error/10 text-error",
        label: "Rejected",
      };
    case "unverified":
    default:
      return {
        classes: "border-border-default bg-surface-2 text-foreground-muted",
        label: "Not submitted",
      };
  }
}

const BASE_CLASSES =
  "inline-flex h-7 items-center gap-1.5 rounded-badge border px-2 text-xs font-medium uppercase tracking-[0.05em]";

/**
 * Render a verification status pill for one Credential.
 *
 * @param status - Verification status ("unverified" | "pending" | "verified" | "rejected").
 * @param expired - Whether the credential's expiry date has passed.
 */
export function CredentialStatusBadge({
  status,
  expired,
}: {
  status: string;
  expired: boolean;
}) {
  const variant = resolveVariant(status);
  const showExpired = expired && status === "verified";

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={`${BASE_CLASSES} ${variant.classes}`}>
        {variant.label}
      </span>
      {showExpired ? (
        <span
          className={`${BASE_CLASSES} border-border-default bg-surface-2 text-foreground-muted`}
        >
          Expired
        </span>
      ) : null}
    </span>
  );
}
