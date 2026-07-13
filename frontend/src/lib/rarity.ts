/**
 * Buyer-facing rarity badge mapping.
 *
 * Frameworks carry an internal rarity score (0–1, higher = more original) that
 * also feeds the near-duplicate moderation gate. Buyers should never see the
 * raw number — it is meaningless out of context and can discourage a purchase.
 * Instead we surface a positive-only badge: original work earns "Rare" or
 * "Distinct"; anything below the Distinct floor earns no badge at all, so a
 * listing is never stamped with a negative label.
 *
 * Maps to: FR-FWK originality signal (full-spec Framework Score — Rarity term).
 */

/** Positive rarity tiers a buyer can see. Below Distinct there is no badge. */
export type RarityTier = "rare" | "distinct";

/** A resolved badge: the tier, its display word, and a plain-language blurb. */
export interface RarityBadge {
  tier: RarityTier;
  label: string;
  blurb: string;
}

/** Score at/above which a framework reads as "Rare". */
const RARE_MIN = 0.8;
/** Score at/above which a framework reads as "Distinct". */
const DISTINCT_MIN = 0.6;

/**
 * Resolve a rarity score into a positive buyer-facing badge, or null.
 *
 * @param score - Raw rarity score as delivered by the API (`string | null`),
 *   or a number. Unparseable, missing, or below-Distinct values yield null.
 * @returns The badge to render, or null when no badge should show.
 */
export function rarityBadge(
  score: string | number | null | undefined,
): RarityBadge | null {
  if (score === null || score === undefined || score === "") {
    return null;
  }
  const value = typeof score === "string" ? Number(score) : score;
  if (!Number.isFinite(value)) {
    return null;
  }
  if (value >= RARE_MIN) {
    return {
      tier: "rare",
      label: "Rare",
      blurb: "Few similar frameworks on Auracles.",
    };
  }
  if (value >= DISTINCT_MIN) {
    return {
      tier: "distinct",
      label: "Distinct",
      blurb: "Stands apart from most frameworks on Auracles.",
    };
  }
  return null;
}
