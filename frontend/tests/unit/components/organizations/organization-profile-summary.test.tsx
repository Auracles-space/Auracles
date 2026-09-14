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
vi.mock("@/lib/generated/sdk.gen", () => ({ changeOrgSlugV1OrgsOrgIdSlugPatch: vi.fn() }));

/** Context for a verified org with the given caller role. */
function context(role: string) {
  return {
    orgId: "org-1",
    role,
    org: { id: "org-1", name: "Meridian Audit", slug: "meridian", created_at: "2026-03-02T09:00:00Z" },
    kybStatus: "verified",
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
