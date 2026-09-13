/**
 * Team capability toggles: the hint says why a control is disabled.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TeamCapabilityToggles } from "@/components/modules/organizations/team-capability-toggles";

const team = { id: "t1", name: "Reviewers", capabilities: [] } as never;

describe("TeamCapabilityToggles", () => {
  it("tells suspended, revoked, and never-activated capabilities apart", () => {
    render(
      <TeamCapabilityToggles
        onToggle={vi.fn()}
        orgCapabilities={{ contributor: "suspended", operator: "revoked" }}
        team={team}
      />,
    );

    expect(screen.getByText(/contributor is suspended for the organization/i)).toBeInTheDocument();
    expect(screen.getByText(/operator was revoked for the organization/i)).toBeInTheDocument();
    expect(screen.getByText(/activate attestor for the organization first/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /enable contributor/i })).toBeDisabled();
  });

  it("shows no hint when every capability is active", () => {
    render(
      <TeamCapabilityToggles
        onToggle={vi.fn()}
        orgCapabilities={{ contributor: "active", operator: "active", attestor: "active" }}
        team={team}
      />,
    );

    expect(screen.queryByText(/for the organization/i)).not.toBeInTheDocument();
  });
});
