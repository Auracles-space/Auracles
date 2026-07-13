/**
 * Unit coverage for the buyer-facing RarityBadge component.
 *
 * The badge is positive-only: it renders "Rare"/"Distinct" for original work
 * and nothing at all below the Distinct floor, so a listing is never labelled
 * with a discouraging word.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RarityBadge } from "@/components/modules/frameworks/rarity-badge";

describe("RarityBadge", () => {
  it("renders the tier word for a high-originality score", () => {
    render(<RarityBadge score="0.8734" />);
    expect(screen.getByText("Rare")).toBeInTheDocument();
  });

  it("renders nothing below the Distinct floor", () => {
    const { container } = render(<RarityBadge score="0.42" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a missing score", () => {
    const { container } = render(<RarityBadge score={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
