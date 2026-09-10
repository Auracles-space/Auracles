/**
 * Tests for the organization profile tab.
 *
 * Verifies the profile view mounts the capabilities activation card for
 * eligible organization admins and owners.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useOrganization } from "./organization-context";
import { OrganizationProfile } from "./organization-profile";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  updateOrganizationV1OrgsOrgIdPatch: vi.fn(),
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost: vi.fn(),
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost: vi.fn(),
}));
vi.mock("./organization-context", () => ({ useOrganization: vi.fn() }));
vi.mock("./organization-logo-uploader", () => ({
  OrganizationLogoUploader: () => null,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useOrganization).mockReturnValue({
    orgId: "org-1",
    role: "owner",
    org: {
      id: "org-1",
      name: "Test Org",
      website: null,
      description: null,
      logo_url: null,
      suspended_at: null,
    },
    capabilities: {},
    // Verified: activation is only offered to a verified org.
    kybStatus: "verified",
    isSuspended: false,
    refreshOrganization: vi.fn().mockResolvedValue(undefined),
  } as never);
});

describe("OrganizationProfile", () => {
  it("renders the Capabilities card for an owner", () => {
    render(<OrganizationProfile />);
    expect(screen.getByText("Capabilities")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Activate Contributor capability" }),
    ).toBeTruthy();
  });
});
