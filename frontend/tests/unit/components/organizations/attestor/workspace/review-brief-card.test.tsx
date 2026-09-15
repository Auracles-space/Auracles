/**
 * Unit coverage for the reviewer's brief card: a long brief stays readable
 * behind Read more instead of stretching the three-column card.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewBriefCard } from "@/components/modules/organizations/attestor/workspace/review-brief-card";

describe("ReviewBriefCard", () => {
  it("puts a long brief field behind Read more", () => {
    render(
      <ReviewBriefCard
        brief={{
          what_it_does: "Covers CAC ownership checks. ".repeat(30),
          use_case: "Seed-stage diligence.",
          desired_outcome: "A quality attestation.",
        }}
      />,
    );

    expect(screen.getAllByRole("button", { name: /read more/i })).toHaveLength(1);
    expect(screen.getByText("Seed-stage diligence.")).toBeInTheDocument();
  });
});
