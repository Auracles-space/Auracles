import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingPrompt } from "@/components/modules/auth/onboarding-prompt";
import { getCurrentUser } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addRoleV1AuthRolesPost: vi.fn(),
  getCurrentUser: vi.fn(),
}));

describe("OnboardingPrompt", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset();
  });

  it("keeps browse and preview available once the user has a role", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      data: { roles: ["operator"], pending_roles: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<OnboardingPrompt />);

    expect(
      await screen.findByText(/complete your profile/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/verify your identity/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /browse frameworks/i }),
    ).toHaveAttribute("href", "/explore");
  });

  it("gates onboarding behind role selection for a roleless user", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      data: { roles: [], pending_roles: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<OnboardingPrompt />);

    // The role picker shows; the KYC/browse steps stay hidden until a role is saved.
    expect(
      await screen.findByText(/how will you use auracles/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/verify your identity/i)).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("link", { name: /browse frameworks/i }),
    ).not.toBeInTheDocument();
  });
});
