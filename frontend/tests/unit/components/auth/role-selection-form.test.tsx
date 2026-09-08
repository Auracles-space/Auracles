/**
 * Unit coverage for the shared self-assignable role picker.
 *
 * The form is the single write path for Contributor/Operator role changes, so
 * these cases pin the three things every caller depends on: it offers only the
 * roles it was given, it mints a fresh access token before handing control
 * back, and a failed assignment never reports success.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RoleSelectionForm } from "@/components/modules/auth/role-selection-form";
import { refreshAccessToken } from "@/lib/auth/refresh-client";
import { addRoleV1AuthRolesPost } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/auth/refresh-client", () => ({
  refreshAccessToken: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  addRoleV1AuthRolesPost: vi.fn(),
}));

function mockAssignmentOk(): void {
  vi.mocked(addRoleV1AuthRolesPost).mockResolvedValue({
    data: { role: "operator" },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("RoleSelectionForm", () => {
  beforeEach(() => {
    vi.mocked(addRoleV1AuthRolesPost).mockReset();
    vi.mocked(refreshAccessToken).mockReset();
    vi.mocked(refreshAccessToken).mockResolvedValue(true);
  });

  it("offers only the roles it was given", () => {
    render(
      <RoleSelectionForm
        availableRoles={["operator"]}
        description="Pick what you need."
        heading="Add a role"
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/Operator/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Contributor/)).not.toBeInTheDocument();
  });

  it("refuses an empty submission without calling the API", async () => {
    const onSaved = vi.fn();
    render(
      <RoleSelectionForm
        availableRoles={["contributor", "operator"]}
        description="Pick what you need."
        heading="Add a role"
        onSaved={onSaved}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/pick at least one/i);
    expect(addRoleV1AuthRolesPost).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("assigns each selected role, then mints a token carrying it", async () => {
    mockAssignmentOk();
    const onSaved = vi.fn();
    render(
      <RoleSelectionForm
        availableRoles={["contributor", "operator"]}
        description="Pick what you need."
        heading="Add a role"
        onSaved={onSaved}
      />,
    );

    fireEvent.click(screen.getByLabelText(/Contributor/));
    fireEvent.click(screen.getByLabelText(/Operator/));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(addRoleV1AuthRolesPost).toHaveBeenCalledTimes(2);
    // RBAC reads roles from the JWT claims, so a new role is inert until the
    // access token is reissued. The refresh must happen before the caller
    // navigates, or the very action the user unlocked still 403s.
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
  });

  it("surfaces a failed assignment and does not report success", async () => {
    vi.mocked(addRoleV1AuthRolesPost).mockResolvedValue({
      data: undefined,
      error: { detail: "Role already assigned." },
      response: new Response(null, { status: 409 }),
    } as never);
    const onSaved = vi.fn();
    render(
      <RoleSelectionForm
        availableRoles={["operator"]}
        description="Pick what you need."
        heading="Add a role"
        onSaved={onSaved}
      />,
    );

    fireEvent.click(screen.getByLabelText(/Operator/));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });
});
