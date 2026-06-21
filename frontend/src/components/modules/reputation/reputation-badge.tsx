/**
 * Reputation badge.
 *
 * Renders the headline 0-100 reputation score plus the names of its strongest
 * contributing factors, or a neutral "New" pill while the subject is still
 * provisional (low evidence). Surfaces labels only — never weights or raw
 * sub-values (full-spec §3234, anti-gaming).
 *
 * Maps to: BR-ATT-005.
 */
import type { ReputationFactorLabel, ReputationSummary } from "@/lib/generated/types.gen";

import { formatLabel } from "@/lib/marketplace/format";

interface ReputationBadgeProps {
  /** Headline score (decimal string or number), or null when provisional/new. */
  score: ReputationSummary["score"] | number;
  /** Whether the subject lacks enough evidence for a stable score. */
  isProvisional: boolean;
  /** Contributing factors with public strength labels. */
  factors: ReputationFactorLabel[];
}

type ReputationTier = "low" | "medium" | "high";

/**
 * Bucket a 0-100 score into a trust tier with its color classes.
 *
 * Color alone never carries the meaning — callers also expose the tier word in
 * the accessible label (WCAG 1.4.1, use of color).
 *
 * @param score - Rounded reputation score on a 0-100 scale.
 */
function reputationTier(score: number): {
  tier: ReputationTier;
  className: string;
} {
  if (score >= 70) {
    return {
      tier: "high",
      className: "border-success/30 bg-success/10 text-success",
    };
  }
  if (score >= 40) {
    return {
      tier: "medium",
      className: "border-warning/30 bg-warning/10 text-warning",
    };
  }
  return {
    tier: "low",
    className: "border-error/30 bg-error/10 text-error",
  };
}

/**
 * Reputation trust badge for Explore cards, detail pages, and profiles.
 *
 * @param props - Score, provisional flag, and factor labels from the API.
 */
export function ReputationBadge({
  score,
  isProvisional,
  factors,
}: ReputationBadgeProps) {
  const numericScore = score === null || score === undefined ? null : Number(score);

  if (isProvisional || numericScore === null || Number.isNaN(numericScore)) {
    return (
      <span
        className="inline-flex min-h-6 items-center rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-subtle"
        title="Not enough activity yet for a reputation score"
      >
        New
      </span>
    );
  }

  const rounded = Math.round(numericScore);
  const { tier, className } = reputationTier(rounded);

  const strongFactors = factors
    .filter((factor) => factor.label === "strong")
    .map((factor) => formatLabel(factor.factor));

  return (
    <span
      className={`inline-flex min-h-6 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] ${className}`}
      data-tier={tier}
      aria-label={`Reputation ${rounded} out of 100, ${tier}`}
    >
      <span className="text-xs font-bold">{rounded}</span>
      {strongFactors.length > 0 ? (
        <span className="font-medium normal-case tracking-normal opacity-80">
          · {strongFactors.join(", ")}
        </span>
      ) : null}
    </span>
  );
}
