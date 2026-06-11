import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewSummary } from "@/components/modules/explore/framework-card";

describe("ReviewSummary", () => {
  it("renders average score and pluralized review count", () => {
    render(<ReviewSummary averageScore="4.50" reviewCount={2} />);

    expect(screen.getByText("4.50 (2 reviews)")).toBeInTheDocument();
  });

  it("renders the empty review state", () => {
    render(<ReviewSummary averageScore={null} reviewCount={0} />);

    expect(screen.getByText("No reviews yet")).toBeInTheDocument();
  });
});
