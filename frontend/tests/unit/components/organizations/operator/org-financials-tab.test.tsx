import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const caps: { current: Record<string, string> } = { current: {} };
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin", capabilities: caps.current }),
}));
vi.mock("@/components/modules/organizations/operator/org-billing-section", () => ({
  OrgBillingSection: () => <div data-testid="billing" />,
}));
vi.mock("@/components/modules/organizations/attestor/org-attestor-financials-tab", () => ({
  OrgAttestorFinancialsTab: () => <div data-testid="earnings" />,
}));
import { OrgFinancialsTab } from "@/components/modules/organizations/operator/org-financials-tab";

describe("OrgFinancialsTab", () => {
  it("renders Billing when operator is active", () => {
    caps.current = { operator: "active" };
    render(<OrgFinancialsTab orgId="org-1" />);
    expect(screen.getByTestId("billing")).toBeInTheDocument();
    expect(screen.queryByTestId("earnings")).toBeNull();
  });

  it("renders Earnings when attestor is active and Billing when both active", () => {
    caps.current = { operator: "active", attestor: "active" };
    render(<OrgFinancialsTab orgId="org-1" />);
    expect(screen.getByTestId("billing")).toBeInTheDocument();
    expect(screen.getByTestId("earnings")).toBeInTheDocument();
  });
});
