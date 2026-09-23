/**
 * Capability wind-down panel tests.
 *
 * An owner could not close their own organization: the close refuses while a
 * capability is active and only an admin could change one, which also blocked
 * account deletion behind it. These cover the control that breaks that loop.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationCapabilityWindDown } from "@/components/modules/organizations/organization-capability-winddown";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { withdrawContributorCapabilityV1OrgsOrgIdContributorCapabilityWithdrawPost as withdrawContributor } from "@/lib/generated/sdk.gen";

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  withdrawAttestorCapabilityV1OrgsOrgIdAttestorCapabilityWithdrawPost: vi.fn(),
  withdrawContributorCapabilityV1OrgsOrgIdContributorCapabilityWithdrawPost: vi.fn(),
  withdrawOperatorCapabilityV1OrgsOrgIdOperatorCapabilityWithdrawPost: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

function mockOrg(overrides: Record<string, unknown> = {}) {
  vi.mocked(useOrganization).mockReturnValue({
    orgId: "org-1",
    org: { id: "org-1", name: "Acme Advisory" },
    role: "owner",
    isSuspended: false,
    capabilities: { contributor: "active", operator: "active" },
    ...overrides,
  } as never);
}

describe("OrganizationCapabilityWindDown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(withdrawContributor).mockResolvedValue({
      response: { ok: true },
      error: undefined,
    } as never);
  });

  it("offers a stand-down for each active capability", () => {
    mockOrg();

    render(<OrganizationCapabilityWindDown onChange={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: /stand down contributor/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /stand down operator/i }),
    ).toBeInTheDocument();
  });

  it("stands a capability down and tells the parent to refetch", async () => {
    const onChange = vi.fn();
    mockOrg();

    render(<OrganizationCapabilityWindDown onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /stand down contributor/i }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(withdrawContributor).toHaveBeenCalledWith({
      path: { org_id: "org-1" },
      headers: { Authorization: "Bearer access-token" },
    });
  });

  it("says the organization is ready to close when nothing is active", () => {
    // The whole point of the panel: an owner needs to see that the blocker
    // the close error names is gone.
    mockOrg({ capabilities: { contributor: "withdrawn" } });

    render(<OrganizationCapabilityWindDown onChange={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /stand down/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no active capabilities/i)).toBeInTheDocument();
  });

  it("renders nothing for a non-owner", () => {
    mockOrg({ role: "admin" });

    const { container } = render(
      <OrganizationCapabilityWindDown onChange={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
