import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingPrompt } from "@/components/modules/auth/onboarding-prompt";
import { getCurrentUser } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/auth/refresh-client", () => ({
  refreshAccessToken: vi.fn(async () => true),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addRoleV1AuthRolesPost: vi.fn(),
  getCurrentUser: vi.fn(),
}));

function mockCurrentUser(data: Record<string, unknown>): void {
  vi.mocked(getCurrentUser).mockResolvedValue({
    data,
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("OnboardingPrompt", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset();
  });

  it("keeps browse and preview available once the user has a role", async () => {
    mockCurrentUser({ pending_roles: [], roles: ["operator"] });

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
    mockCurrentUser({ pending_roles: [], roles: [] });

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

  it("reports a finished step as done instead of outstanding work", async () => {
    // The bug this pins: a verified, named user bounced here for an unrelated
    // reason was told to go and verify their identity, which they had already
    // done. Completed steps must read as complete.
    mockCurrentUser({
      display_name: "Victor",
      email_verified: true,
      kyc_status: "verified",
      pending_roles: [],
      roles: ["contributor"],
    });

    render(<OnboardingPrompt />);

    await screen.findByText(/verify your identity/i);
    expect(screen.getAllByText(/^done$/i).length).toBeGreaterThanOrEqual(2);
    expect(
      screen.queryByRole("link", { name: /^verify identity$/i }),
    ).not.toBeInTheDocument();
  });

  it("offers the missing role when the block was a role, not identity", async () => {
    mockCurrentUser({
      display_name: "Victor",
      email_verified: true,
      kyc_status: "verified",
      pending_roles: [],
      roles: ["contributor"],
    });

    render(<OnboardingPrompt errorCode="role_required" returnTo="/projects/new" />);

    // Only the role they lack is offered, and the identity step stays done.
    expect(await screen.findByLabelText(/Operator/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Contributor/)).not.toBeInTheDocument();
  });

  it("still shows the identity action when KYC is genuinely unfinished", async () => {
    mockCurrentUser({
      display_name: "Victor",
      email_verified: true,
      kyc_status: "unverified",
      pending_roles: [],
      roles: ["contributor"],
    });

    render(<OnboardingPrompt returnTo="/projects/new" />);

    expect(
      await screen.findByRole("link", { name: /^verify identity$/i }),
    ).toHaveAttribute("href", "/settings/kyc?next=%2Fprojects%2Fnew");
  });
});
