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
  it("shows the outcome once the attestation is accepted", () => {
    render(<AttestationBadge badge={badge({ status: "attested", outcome: "approved" })} />);

    expect(screen.getByText(/Attested/i)).toBeInTheDocument();
    expect(screen.getByText(/approved/i)).toBeInTheDocument();
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
