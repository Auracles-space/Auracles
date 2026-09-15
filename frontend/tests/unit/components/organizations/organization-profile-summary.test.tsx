/**
 * Organization profile summary — owner-only slug change entry point.
 *
 * Only owners may change the public address (Decision 5), so admins and
 * members must never see the control.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationProfileSummary } from "@/components/modules/organizations/organization-profile-summary";
import { useOrganization } from "@/components/modules/organizations/organization-context";

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: vi.fn(),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({})),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  changeOrgCountryV1OrgsOrgIdCountryPatch: vi.fn(),
  changeOrgSlugV1OrgsOrgIdSlugPatch: vi.fn(),
}));

/** Context for a verified org with the given caller role. */
function context(role: string, kybStatus = "verified") {
  return {
    orgId: "org-1",
    role,
    org: { id: "org-1", name: "Meridian Audit", slug: "meridian", country: "NG", created_at: "2026-03-02T09:00:00Z" },
    kybStatus,
    kybVerifiedAt: null,
    memberCount: 3,
    refreshOrganization: vi.fn().mockResolvedValue(undefined),
  };
}

describe("OrganizationProfileSummary slug change", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers owners a 44px Change address button that opens the dialog", () => {
    vi.mocked(useOrganization).mockReturnValue(context("owner") as never);
    render(<OrganizationProfileSummary />);

    const button = screen.getByRole("button", { name: "Change address" });
    expect(button.className).toMatch(/min-h-11/);
    fireEvent.click(button);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it.each(["admin", "member"])("hides the control from %s", (role) => {
    vi.mocked(useOrganization).mockReturnValue(context(role) as never);
    render(<OrganizationProfileSummary />);

    expect(screen.queryByRole("button", { name: "Change address" })).toBeNull();
  });
});

describe("OrganizationProfileSummary country", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the country by name", () => {
    vi.mocked(useOrganization).mockReturnValue(context("member") as never);
    render(<OrganizationProfileSummary />);

    expect(screen.getByText("Nigeria")).toBeInTheDocument();
  });

  it.each(["unverified", "rejected"])(
    "lets an owner open the country dialog while verification is %s",
    (kybStatus) => {
      vi.mocked(useOrganization).mockReturnValue(context("owner", kybStatus) as never);
      render(<OrganizationProfileSummary />);

      const button = screen.getByRole("button", { name: "Change country" });
      expect(button.className).toMatch(/min-h-11/);
      fireEvent.click(button);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    },
  );

  it.each(["pending", "verified"])(
    "locks the country once verification is %s",
    (kybStatus) => {
      vi.mocked(useOrganization).mockReturnValue(context("owner", kybStatus) as never);
      render(<OrganizationProfileSummary />);

      expect(screen.queryByRole("button", { name: "Change country" })).toBeNull();
      expect(screen.getByText(/Locked after verification/)).toBeInTheDocument();
    },
  );

  it("hides the country control from admins", () => {
    vi.mocked(useOrganization).mockReturnValue(context("admin", "unverified") as never);
    render(<OrganizationProfileSummary />);

    expect(screen.queryByRole("button", { name: "Change country" })).toBeNull();
  });
});
