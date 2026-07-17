/**
 * Tests for the organization capability activation card.
 *
 * Verifies owner/admin visibility, per-capability status rendering, and the
 * confirm-gated activation flow.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useOrganization } from "./organization-context";
import {
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost as activateContributor,
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost as activateOperator,
} from "@/lib/generated/sdk.gen";
import { OrganizationCapabilities } from "./organization-capabilities";

const { refresh, refreshOrganization, toastSuccess, toastError } = vi.hoisted(() => ({
  refresh: vi.fn(),
  refreshOrganization: vi.fn().mockResolvedValue(undefined),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError }),
}));
vi.mock("./organization-context", () => ({ useOrganization: vi.fn() }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost: vi.fn(),
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost: vi.fn(),
}));

/** Set the org context the component reads. */
function setOrg(
  overrides: Partial<{
    role: string;
    capabilities: Record<string, string>;
    isSuspended: boolean;
  }> = {},
) {
  vi.mocked(useOrganization).mockReturnValue({
    orgId: "org-1",
    role: "owner",
    capabilities: {},
    isSuspended: false,
    refreshOrganization,
    ...overrides,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  refreshOrganization.mockResolvedValue(undefined);
});

describe("OrganizationCapabilities", () => {
  it("shows an Activate button for a capability that is not active", () => {
    setOrg({ capabilities: {} });
    render(<OrganizationCapabilities />);
    expect(
      screen.getByRole("button", { name: "Activate Contributor capability" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Activate Operator capability" }),
    ).toBeTruthy();
  });

  it("shows an Active pill and no Activate button when the capability is active", () => {
    setOrg({ capabilities: { operator: "active" } });
    render(<OrganizationCapabilities />);
    expect(screen.getByText("Active")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Activate Operator capability" }),
    ).toBeNull();
  });

  it("shows a Suspended pill and no Activate button when the capability is suspended", () => {
    setOrg({ capabilities: { contributor: "suspended" } });
    render(<OrganizationCapabilities />);
    expect(screen.getByText("Suspended")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Activate Contributor capability" }),
    ).toBeNull();
  });

  it("shows a Not active pill for a capability with no status", () => {
    setOrg({ capabilities: {} });
    render(<OrganizationCapabilities />);
    expect(screen.getAllByText("Not active").length).toBe(2);
  });

  it("renders nothing for a non-admin member", () => {
    setOrg({ role: "member" });
    const { container } = render(<OrganizationCapabilities />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the org is suspended", () => {
    setOrg({ role: "owner", isSuspended: true });
    const { container } = render(<OrganizationCapabilities />);
    expect(container).toBeEmptyDOMElement();
  });

  it("activates a capability after confirmation, then toasts and refreshes", async () => {
    setOrg({ capabilities: {} });
    vi.mocked(activateContributor).mockResolvedValue({
      response: { ok: true },
    } as never);
    render(<OrganizationCapabilities />);

    fireEvent.click(
      screen.getByRole("button", { name: "Activate Contributor capability" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Activate Contributor" }));

    await waitFor(() => expect(activateContributor).toHaveBeenCalledTimes(1));
    expect(activateContributor).toHaveBeenCalledWith({
      path: { org_id: "org-1" },
      headers: { Authorization: "Bearer test" },
    });
    expect(activateOperator).not.toHaveBeenCalled();
    expect(refreshOrganization).toHaveBeenCalledTimes(1);
    expect(toastSuccess).toHaveBeenCalledWith(
      "Contributor capability activated.",
    );
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("surfaces the error and keeps the dialog open when activation fails", async () => {
    setOrg({ capabilities: {} });
    vi.mocked(activateOperator).mockResolvedValue({
      response: { ok: false },
      error: { detail: { error_code: "rate_limited" } },
    } as never);
    render(<OrganizationCapabilities />);

    fireEvent.click(
      screen.getByRole("button", { name: "Activate Operator capability" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Activate Operator" }));

    expect(await screen.findByText("rate_limited")).toBeTruthy();
    expect(screen.getByText("Activate Operator capability?")).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });
});
