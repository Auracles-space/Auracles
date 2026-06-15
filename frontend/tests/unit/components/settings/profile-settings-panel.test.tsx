import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileSettingsPanel } from "@/components/modules/settings/profile-settings-panel";
import { authTokenStore } from "@/lib/auth/token-store";
import {
  getCurrentUser,
  resendVerificationV1AuthResendVerificationPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer access-token" })),
}));

vi.mock("@/lib/auth/refresh-client", () => ({
  refreshAccessToken: vi.fn(async () => true),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getCurrentUser: vi.fn(),
  resendVerificationV1AuthResendVerificationPost: vi.fn(),
}));

describe("ProfileSettingsPanel", () => {
  beforeEach(() => {
    authTokenStore.setState({
      accessToken: null,
      expiresAt: null,
      roles: [],
      totpVerified: false,
      userId: null,
    });
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(resendVerificationV1AuthResendVerificationPost).mockReset();
    vi.mocked(getCurrentUser).mockResolvedValue({
      data: {
        avatar_url: null,
        deactivated_at: null,
        display_name: "Ada Markets",
        email: "ada@example.com",
        email_verified: false,
        id: "00000000-0000-4000-8000-000000000001",
        kyc_status: "pending",
        roles: ["operator", "contributor"],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(resendVerificationV1AuthResendVerificationPost).mockResolvedValue({
      data: { message: "If email is valid, verification sent." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("renders identity, status summaries, and resends verification for unverified email", async () => {
    render(<ProfileSettingsPanel />);

    expect(await screen.findByRole("heading", { name: /private profile/i })).toBeVisible();
    expect(screen.getByText("Ada Markets")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("Contributor")).toBeInTheDocument();
    expect(screen.getByText("Operator")).toBeInTheDocument();

    const emailSection = screen.getByRole("region", { name: /email verification/i });
    expect(within(emailSection).getByText(/not verified/i)).toBeInTheDocument();

    fireEvent.click(
      within(emailSection).getByRole("button", { name: /resend verification email/i }),
    );

    await waitFor(() => {
      expect(resendVerificationV1AuthResendVerificationPost).toHaveBeenCalledWith({
        body: { email: "ada@example.com" },
      });
    });

    const kycSection = screen.getByRole("region", { name: /kyc status/i });
    expect(within(kycSection).getByText(/pending review/i)).toBeInTheDocument();
    expect(
      within(kycSection).getByRole("link", { name: /continue kyc/i }),
    ).toHaveAttribute("href", "/settings/kyc");
  });
});
