/**
 * Unit coverage for the settings roles panel.
 *
 * This panel is the only place in the product where an existing account can
 * take on a second role, so the cases below pin that it shows what the user
 * already holds and offers exactly what they are still missing.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountRolesPanel } from "@/components/modules/settings/account-roles-panel";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("next=%2Fprojects%2Fnew"),
}));

vi.mock("@/lib/auth/refresh-client", () => ({
  refreshAccessToken: vi.fn(async () => true),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addRoleV1AuthRolesPost: vi.fn(),
}));

function mockSession(roles: string[], pendingRoles: string[] = []): void {
  vi.mocked(loadCurrentUserSession).mockResolvedValue({
    display_name: "Victor",
    email: "victor@auracles.space",
    email_verified: true,
    kyc_status: "verified",
    pending_roles: pendingRoles,
    roles,
  } as never);
}

describe("AccountRolesPanel", () => {
  beforeEach(() => {
    vi.mocked(loadCurrentUserSession).mockReset();
  });

  it("offers the role the user does not hold yet", async () => {
    mockSession(["contributor"]);

    render(<AccountRolesPanel />);

    await screen.findByRole("heading", { name: /how you use auracles/i });
    expect(screen.getByLabelText(/Operator/)).toBeInTheDocument();
    // The role they already hold is reported as active, never re-offered as a
    // checkbox that would 409 on submit.
    expect(screen.queryByLabelText(/Contributor/)).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("list")).getByText(/^Contributor$/),
    ).toBeInTheDocument();
  });

  it("stops offering roles once the user holds both", async () => {
    mockSession(["contributor", "operator"]);

    render(<AccountRolesPanel />);

    await screen.findByRole("heading", { name: /how you use auracles/i });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /add role/i })).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/both marketplace roles/i)).toBeInTheDocument();
  });

  it("marks an Attestor application as awaiting approval", async () => {
    // Attestor is the only role gated on approval, so it is the only thing
    // `pending_roles` carries — the contract guarantees it never overlaps the
    // active roles.
    mockSession(["contributor"], ["attestor"]);

    render(<AccountRolesPanel />);

    await screen.findByRole("heading", { name: /how you use auracles/i });
    const active = within(screen.getByRole("list"));
    expect(active.getByText(/^Contributor$/)).toBeInTheDocument();
    expect(active.getByText(/Attestor — awaiting approval/)).toBeInTheDocument();
  });

  it("treats a role awaiting approval as already requested", async () => {
    // Attestor is org-granted, but a pending self-role must not be offered
    // again either — a second request is a 409, not a second application.
    mockSession(["contributor"], ["operator"]);

    render(<AccountRolesPanel />);

    await screen.findByRole("heading", { name: /how you use auracles/i });
    expect(screen.queryByLabelText(/Operator/)).not.toBeInTheDocument();
  });
});
