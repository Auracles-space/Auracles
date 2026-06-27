import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewSummary } from "@/components/modules/explore/framework-card";

describe("ReviewSummary", () => {
  it("renders the score as stars and the review count", () => {
    render(<ReviewSummary averageScore="4.50" reviewCount={2} />);

    expect(screen.getByLabelText("Rating: 4.5 out of 5 stars")).toBeInTheDocument();
    expect(screen.getByText("(2)")).toBeInTheDocument();
  });

  it("renders the empty review state", () => {
    render(<ReviewSummary averageScore={null} reviewCount={0} />);

    expect(screen.getByText("No reviews yet")).toBeInTheDocument();
  });
});
