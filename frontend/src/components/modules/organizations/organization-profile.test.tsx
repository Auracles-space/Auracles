/**
 * Tests for the organization profile tab.
 *
 * Verifies the profile view mounts the capabilities activation card for
 * eligible organization admins and owners.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** Baseline owner context for a verified org. */
function ownerContext() {
  return {
    orgId: "org-1",
    role: "owner",
    org: {
      id: "org-1",
      name: "Test Org",
      slug: "test-org",
      created_at: "2026-03-02T09:00:00Z",
      website: null,
      description: null,
      logo_url: null,
      suspended_at: null,
    },
    capabilities: {},
    // Verified: activation is only offered to a verified org.
    kybStatus: "verified",
    kybVerifiedAt: "2026-04-15T12:00:00Z",
    memberCount: 7,
    isSuspended: false,
    refreshOrganization: vi.fn().mockResolvedValue(undefined),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useOrganization).mockReturnValue(ownerContext() as never);
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

describe("OrganizationProfile summary", () => {
  it("shows the public profile URL with copy and open controls", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<OrganizationProfile />);

    const url = `${window.location.origin}/orgs/test-org`;
    expect(screen.getByText(url)).toBeInTheDocument();
    const open = screen.getByRole("link", { name: /open public profile/i });
    expect(open).toHaveAttribute("href", "/orgs/test-org");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open.className).toMatch(/min-h-11/);

    const copy = screen.getByRole("button", { name: /copy public profile url/i });
    expect(copy.className).toMatch(/min-h-11/);
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(url));
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("shows created and verified dates, member count, and the caller's role", () => {
    render(<OrganizationProfile />);

    expect(screen.getByText(/2 Mar 2026/)).toBeInTheDocument();
    expect(screen.getByText(/15 Apr 2026/)).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("omits the verified date when the org is not verified", () => {
    vi.mocked(useOrganization).mockReturnValue({
      ...ownerContext(),
      kybStatus: "pending",
      kybVerifiedAt: null,
    } as never);
    render(<OrganizationProfile />);

    expect(screen.queryByText(/15 Apr 2026/)).toBeNull();
    expect(screen.getByText(/2 Mar 2026/)).toBeInTheDocument();
  });
});
