import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AttestorEligibleOrg } from "@/components/modules/organizations/become-attestor";
import { BecomeAttestorPicker } from "@/components/modules/organizations/become-attestor-picker";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const orgs: AttestorEligibleOrg[] = [
  { id: "a", name: "Alpha", attestorStatus: null, kybStatus: "verified", eligible: true },
  { id: "b", name: "Beta", attestorStatus: "pending", kybStatus: "verified", eligible: true },
];

describe("BecomeAttestorPicker", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders each org with the right status label", () => {
    render(<BecomeAttestorPicker orgs={orgs} />);

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText(/Not started/i)).toBeInTheDocument();
    expect(screen.getByText(/Resume/i)).toBeInTheDocument();
  });

  it("routes to an organization's attestor tab when chosen", () => {
    render(<BecomeAttestorPicker orgs={orgs} />);

    fireEvent.click(screen.getByRole("button", { name: /Alpha/i }));

    expect(push).toHaveBeenCalledWith("/dashboard/organizations/a/attestor");
  });

  it("explains an unverified org instead of hiding it, linking to verification", () => {
    render(
      <BecomeAttestorPicker
        orgs={[
          { id: "u", name: "Unverified Co", attestorStatus: null, kybStatus: "pending", eligible: false },
        ]}
      />,
    );

    expect(screen.getByText("Unverified Co")).toBeInTheDocument();
    expect(screen.getByText(/verify the business first/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /verification/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/u/verification",
    );
    expect(screen.queryByRole("button", { name: /Unverified Co/i })).not.toBeInTheDocument();
  });

  it("opens the create dialog from the create tile", () => {
    render(<BecomeAttestorPicker orgs={orgs} />);

    fireEvent.click(screen.getByRole("button", { name: /Create a new organization/i }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
