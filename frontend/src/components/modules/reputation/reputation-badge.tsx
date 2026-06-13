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

  const strongFactors = factors
    .filter((factor) => factor.label === "strong")
    .map((factor) => formatLabel(factor.factor));

  return (
    <span
      className="inline-flex min-h-6 items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success"
      aria-label={`Reputation ${Math.round(numericScore)} out of 100`}
    >
      <span className="text-xs font-bold">{Math.round(numericScore)}</span>
      {strongFactors.length > 0 ? (
        <span className="font-medium normal-case tracking-normal text-success/80">
          · {strongFactors.join(", ")}
        </span>
      ) : null}
    </span>
  );
}
