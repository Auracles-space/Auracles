import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkLicenseCta } from "@/components/modules/explore/framework-license-cta";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  listMyOrganizationsV1OrgsMineGet,
  listOperatorLibrary,
} from "@/lib/generated/sdk.gen";
import type { CurrentUserResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>(
    "@/lib/auth/form-client",
  );
  return { ...actual, getAccessTokenHeaders: vi.fn(() => ({})) };
});

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/explore/fw-1",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOperatorLibrary: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
}));

const okResponse = new Response(null, { status: 200 });

function session(overrides: Partial<CurrentUserResponse> = {}): CurrentUserResponse {
  return {
    avatar_url: null,
    deactivated_at: null,
    display_name: "User",
    email: "user@auracles.test",
    email_verified: true,
    id: "viewer-1",
    kyc_status: "verified",
    pending_roles: [],
    roles: ["operator"],
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(loadCurrentUserSession).mockReset();
  vi.mocked(listOperatorLibrary).mockReset();
  vi.mocked(listMyOrganizationsV1OrgsMineGet).mockReset();
});

const FRAMEWORK_ID = "fw-1";

describe("FrameworkLicenseCta", () => {
  it("shows the license link to an operator who has not licensed it", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(session());
    vi.mocked(listOperatorLibrary).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 20 },
      error: undefined,
      response: okResponse,
    } as never);

    render(
      <FrameworkLicenseCta contributorId="owner-9" frameworkId={FRAMEWORK_ID} />,
    );

    const link = await screen.findByRole("link", { name: /license framework/i });
    expect(link).toHaveAttribute("href", `/checkout/${FRAMEWORK_ID}`);
  });

  it("hides the license link on the viewer's own framework", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session({ id: "owner-9" }),
    );

    render(
      <FrameworkLicenseCta contributorId="owner-9" frameworkId={FRAMEWORK_ID} />,
    );

    await waitFor(() =>
      expect(loadCurrentUserSession).toHaveBeenCalled(),
    );
    expect(
      screen.queryByRole("link", { name: /license framework/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/your framework/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /manage it/i })).toHaveAttribute(
      "href",
      `/dashboard/frameworks/${FRAMEWORK_ID}`,
    );
    expect(listOperatorLibrary).not.toHaveBeenCalled();
  });

  it("offers the library instead when already licensed", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(session());
    vi.mocked(listOperatorLibrary).mockResolvedValue({
      data: {
        items: [
          {
            license_id: "lic-1",
            framework_id: FRAMEWORK_ID,
            title: "X",
            version_at_grant: "1",
            current_version: "1",
            license_type: "standard",
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
      error: undefined,
      response: okResponse,
    } as never);

    render(
      <FrameworkLicenseCta contributorId="owner-9" frameworkId={FRAMEWORK_ID} />,
    );

    const link = await screen.findByRole("link", { name: /in your library/i });
    expect(link).toHaveAttribute("href", "/library");
    expect(
      screen.queryByRole("link", { name: /license framework/i }),
    ).not.toBeInTheDocument();
  });

  it("hides the license link from a member of the owning organization", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(session({ id: "viewer-1" }));
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue({
      data: {
        organizations: [
          { org: { id: "org-7" }, role: "member", capabilities: {} },
        ],
      },
      error: undefined,
      response: okResponse,
    } as never);

    render(
      <FrameworkLicenseCta
        contributorId=""
        contributorOrgId="org-7"
        frameworkId={FRAMEWORK_ID}
      />,
    );

    expect(
      await screen.findByText(/your organization's framework/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /license framework/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /manage it/i })).toHaveAttribute(
      "href",
      `/dashboard/organizations/org-7/frameworks/${FRAMEWORK_ID}`,
    );
    expect(listOperatorLibrary).not.toHaveBeenCalled();
  });

  it("still offers the license link to an operator outside the owning org", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(session({ id: "viewer-1" }));
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue({
      data: {
        organizations: [
          { org: { id: "org-other" }, role: "member", capabilities: {} },
        ],
      },
      error: undefined,
      response: okResponse,
    } as never);
    vi.mocked(listOperatorLibrary).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 20 },
      error: undefined,
      response: okResponse,
    } as never);

    render(
      <FrameworkLicenseCta
        contributorId=""
        contributorOrgId="org-7"
        frameworkId={FRAMEWORK_ID}
      />,
    );

    const link = await screen.findByRole("link", { name: /license framework/i });
    expect(link).toHaveAttribute("href", `/checkout/${FRAMEWORK_ID}`);
  });

  it("offers the Operator role to a signed-in Contributor instead of checkout", async () => {
    // Only Operators can hold a license, and /checkout is role-guarded, so the
    // license link was a wall for a Contributor-only account. The role page is
    // the way through, and it returns them to this framework afterwards.
    vi.mocked(loadCurrentUserSession).mockResolvedValue(
      session({ roles: ["contributor"] }),
    );

    render(
      <FrameworkLicenseCta contributorId="owner-9" frameworkId={FRAMEWORK_ID} />,
    );

    const cta = await screen.findByRole("link", { name: /become an operator/i });
    expect(cta).toHaveAttribute(
      "href",
      "/settings/roles?next=%2Fexplore%2Ffw-1",
    );
    expect(
      screen.queryByRole("link", { name: /license framework/i }),
    ).not.toBeInTheDocument();
    expect(listOperatorLibrary).not.toHaveBeenCalled();
  });

  it("shows the license link to a signed-out visitor", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue(null);

    render(
      <FrameworkLicenseCta contributorId="owner-9" frameworkId={FRAMEWORK_ID} />,
    );

    expect(
      await screen.findByRole("link", { name: /license framework/i }),
    ).toBeInTheDocument();
    expect(listOperatorLibrary).not.toHaveBeenCalled();
  });
});
