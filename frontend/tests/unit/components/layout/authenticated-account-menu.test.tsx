import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthenticatedAccountMenu } from "@/components/modules/layout/authenticated-account-menu";
import { authTokenStore } from "@/lib/auth/token-store";
import {
  getCurrentUser,
  logoutV1AuthLogoutPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer access-token" })),
}));

vi.mock("@/lib/auth/refresh-client", () => ({
  refreshAccessToken: vi.fn(async () => true),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getCurrentUser: vi.fn(),
  logoutV1AuthLogoutPost: vi.fn(),
}));

describe("AuthenticatedAccountMenu", () => {
  beforeEach(() => {
    authTokenStore.setState({
      accessToken: null,
      expiresAt: null,
      roles: [],
      totpVerified: false,
      userId: null,
    });
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(logoutV1AuthLogoutPost).mockReset();
    vi.mocked(getCurrentUser).mockResolvedValue({
      data: {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Ada Markets",
        email: "ada@example.com",
        email_verified: true,
        id: "00000000-0000-4000-8000-000000000001",
        kyc_status: "verified",
        roles: ["operator", "contributor"],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(logoutV1AuthLogoutPost).mockResolvedValue({
      data: { message: "Logged out." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.stubGlobal("location", { assign: vi.fn() });
  });

  it("loads the current user identity and signs out through the auth API", async () => {
    render(<AuthenticatedAccountMenu roles={["operator", "contributor"]} />);

    expect(await screen.findByText("Ada Markets")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Contributor")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));

    await waitFor(() => {
      expect(logoutV1AuthLogoutPost).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
      });
    });
    expect(location.assign).toHaveBeenCalledWith("/login");
  });
});
