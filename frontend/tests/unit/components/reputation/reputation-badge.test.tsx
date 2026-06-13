import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";

describe("ReputationBadge", () => {
  it("shows New when provisional", () => {
    render(<ReputationBadge score={null} isProvisional factors={[]} />);
    expect(screen.getByText(/new/i)).toBeInTheDocument();
  });

  it("shows New when score is null even if not provisional", () => {
    render(
      <ReputationBadge score={null} isProvisional={false} factors={[]} />,
    );
    expect(screen.getByText(/new/i)).toBeInTheDocument();
  });

  it("shows a rounded score and strong factor labels when present", () => {
    render(
      <ReputationBadge
        score="89.60"
        isProvisional={false}
        factors={[
          { factor: "attestations", label: "strong" },
          { factor: "adoption", label: "weak" },
        ]}
      />,
    );
    expect(screen.getByText(/90/)).toBeInTheDocument();
    // Only strong factors surface as supporting labels.
    expect(screen.getByText(/attestations/i)).toBeInTheDocument();
    expect(screen.queryByText(/adoption/i)).not.toBeInTheDocument();
  });
});
