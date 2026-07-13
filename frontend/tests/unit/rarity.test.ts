/**
 * Unit coverage for the buyer-facing rarity badge mapping.
 *
 * Rarity is shown to buyers as a positive-only badge: high-originality
 * frameworks earn "Rare" or "Distinct"; everything else earns no badge so a
 * listing is never stamped with a discouraging label. The raw score never
 * reaches the buyer's eyes.
 */
import { describe, expect, it } from "vitest";

import { rarityBadge } from "@/lib/rarity";

describe("rarityBadge", () => {
  it("returns the Rare tier at and above 0.80", () => {
    expect(rarityBadge("0.9000")?.tier).toBe("rare");
    expect(rarityBadge("0.8000")?.tier).toBe("rare");
  });

  it("returns the Distinct tier from 0.60 up to but not including 0.80", () => {
    expect(rarityBadge("0.7999")?.tier).toBe("distinct");
    expect(rarityBadge("0.6000")?.tier).toBe("distinct");
  });

  it("returns no badge below 0.60", () => {
    expect(rarityBadge("0.5999")).toBeNull();
    expect(rarityBadge("0.0000")).toBeNull();
  });

  it("returns no badge for a missing or unparseable score", () => {
    expect(rarityBadge(null)).toBeNull();
    expect(rarityBadge(undefined)).toBeNull();
    expect(rarityBadge("")).toBeNull();
    expect(rarityBadge("not-a-number")).toBeNull();
  });

  it("carries a human label for each positive tier", () => {
    expect(rarityBadge("0.85")?.label).toBe("Rare");
    expect(rarityBadge("0.65")?.label).toBe("Distinct");
  });
});
