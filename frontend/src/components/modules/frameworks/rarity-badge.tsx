/**
 * Buyer-facing rarity badge.
 *
 * Renders a positive-only originality badge on Framework detail and checkout.
 * A high score reads as "Rare", a merely-above-average score as "Distinct",
 * and anything below the Distinct floor renders nothing — so a listing is
 * never stamped with a discouraging label. The raw score is mapped in
 * {@link rarityBadge}; this component only paints the result.
 *
 * Maps to: FR-FWK originality signal (full-spec Framework Score — Rarity term).
 */
import { rarityBadge } from "@/lib/rarity";

/** Props for {@link RarityBadge}. */
interface RarityBadgeProps {
  /** Raw rarity score from the API (`string | null`) or a number. */
  score: string | number | null | undefined;
}

/**
 * Render the rarity badge for a score, or nothing when no badge applies.
 *
 * @param score - Raw rarity score; unparseable/missing/below-Distinct → no render.
 */
export function RarityBadge({ score }: RarityBadgeProps) {
  const badge = rarityBadge(score);
  if (!badge) {
    return null;
  }
  // Rare gets a slightly stronger accent frame than Distinct; both stay within
  // the existing accent-pill token so the badge matches other status pills.
  const frame =
    badge.tier === "rare"
      ? "border-accent/40 bg-accent/10"
      : "border-accent/20 bg-accent/5";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border ${frame} px-3 py-1.5 text-xs font-semibold text-accent`}
      title={badge.blurb}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />
      {badge.label}
    </span>
  );
}
