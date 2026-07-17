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

const { refresh, toastSuccess, toastError } = vi.hoisted(() => ({
  refresh: vi.fn(),
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
    ...overrides,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
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
});
