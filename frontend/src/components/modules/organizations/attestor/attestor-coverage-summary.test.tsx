import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getOrgAttestorApplication } from "@/lib/generated/sdk.gen";

import { AttestorCoverageSummary } from "./attestor-coverage-summary";

vi.mock("@/lib/generated/sdk.gen", () => ({ getOrgAttestorApplication: vi.fn() }));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1" }),
}));

describe("AttestorCoverageSummary", () => {
  beforeEach(() => {
    vi.mocked(getOrgAttestorApplication).mockReset();
  });

  it("lists the approved sectors, functions, and jurisdictions offers are matched on", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        status: "approved",
        sectors: ["healthcare", "financial_services"],
        functions: ["compliance"],
        jurisdictions: ["global"],
      },
    } as never);

    render(<AttestorCoverageSummary />);

    const summary = await screen.findByRole("region", { name: "Approved coverage" });
    expect(summary).toHaveTextContent("Healthcare");
    expect(summary).toHaveTextContent("Financial Services");
    expect(summary).toHaveTextContent("Compliance");
    expect(summary).toHaveTextContent("Global");
    expect(vi.mocked(getOrgAttestorApplication).mock.calls[0][0]).toMatchObject({
      path: { org_id: "org-1" },
    });
  });

  it("renders nothing when the approved application cannot be loaded", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: undefined,
      error: { detail: "Not found" },
    } as never);

    const { container } = render(<AttestorCoverageSummary />);

    await waitFor(() => expect(getOrgAttestorApplication).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
