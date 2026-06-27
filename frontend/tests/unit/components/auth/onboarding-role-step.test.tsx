import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OnboardingRoleStep } from "@/components/modules/auth/onboarding-role-step";
import { addRoleV1AuthRolesPost, getCurrentUser } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addRoleV1AuthRolesPost: vi.fn(),
  getCurrentUser: vi.fn(),
}));

function mockCurrentUser(roles: string[], pendingRoles: string[] = []): void {
  vi.mocked(getCurrentUser).mockResolvedValue({
    data: { roles, pending_roles: pendingRoles },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("OnboardingRoleStep", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(addRoleV1AuthRolesPost).mockReset();
    vi.stubGlobal("location", { reload: vi.fn() });
  });

  it("renders nothing for a user who already has a role", async () => {
    mockCurrentUser(["operator"]);
    const { container } = render(<OnboardingRoleStep />);

    // Give the mount effect a tick; the step must stay hidden.
    await waitFor(() => expect(getCurrentUser).toHaveBeenCalled());
    expect(
      screen.queryByText(/how will you use auracles/i),
    ).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("assigns each selected role for a roleless user", async () => {
    mockCurrentUser([]);
    vi.mocked(addRoleV1AuthRolesPost).mockResolvedValue({
      data: { role: "operator" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<OnboardingRoleStep />);
    await screen.findByText(/how will you use auracles/i);

    fireEvent.click(screen.getByLabelText(/Contributor/));
    fireEvent.click(screen.getByLabelText(/Operator/));
    fireEvent.click(screen.getByRole("button", { name: /save and continue/i }));

    await waitFor(() =>
      expect(addRoleV1AuthRolesPost).toHaveBeenCalledTimes(2),
    );
    const sentRoles = vi
      .mocked(addRoleV1AuthRolesPost)
      .mock.calls.map((call) => call[0]?.body?.role);
    expect(sentRoles).toEqual(["contributor", "operator"]);
  });
});
