import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import type { ExploreAttestationBadge } from "@/lib/generated/types.gen";
import { AttestationBadge } from "./framework-card";

/** Minimal public badge fixture with overridable fields. */
function badge(overrides: Partial<ExploreAttestationBadge>): ExploreAttestationBadge {
  return {
    id: "att-1",
    status: "attested",
    outcome: "approved",
    report_key: "attestation-reports/att-1.pdf",
    issued_at: "2026-07-16T00:00:00Z",
    attestation_count: 1,
    ...overrides,
  } as ExploreAttestationBadge;
}

describe("AttestationBadge", () => {
  it("renders an icon-only circle with an accessible name when attested", () => {
    render(<AttestationBadge badge={badge({ status: "attested", outcome: "approved" })} />);

    // No visible outcome text — just the labelled check icon.
    expect(screen.getByLabelText("Attested")).toBeInTheDocument();
    expect(screen.queryByText(/approved/i)).not.toBeInTheDocument();
  });

  it("labels a conditional outcome", () => {
    render(
      <AttestationBadge
        badge={badge({ status: "conditionally_attested", outcome: "conditional" })}
      />,
    );

    expect(screen.getByText(/Conditional/i)).toBeInTheDocument();
  });
});
