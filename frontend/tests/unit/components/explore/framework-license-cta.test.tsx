import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkLicenseCta } from "@/components/modules/explore/framework-license-cta";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { listOperatorLibrary } from "@/lib/generated/sdk.gen";
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

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOperatorLibrary: vi.fn(),
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
