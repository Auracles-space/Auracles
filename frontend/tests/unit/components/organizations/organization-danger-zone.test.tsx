/**
 * Organization danger zone — ownership transfer and deactivation guard.
 *
 * The members endpoint returns `{ members: [...] }`; the transfer form must
 * read that envelope, show a load failure instead of an empty select, send
 * the chosen member to the API, and surface server errors through
 * `describeGeneratedError`. Deactivation stays disabled until the owner has
 * typed the confirmation phrase.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationDangerZone } from "@/components/modules/organizations/organization-danger-zone";
import {
  deactivateOrganizationV1OrgsOrgIdDelete,
  listMembersV1OrgsOrgIdMembersGet,
  transferOwnershipV1OrgsOrgIdTransferOwnershipPost,
} from "@/lib/generated/sdk.gen";

const routerPush = vi.fn();
const routerRefresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, refresh: routerRefresh }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "described server error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({
    orgId: "org-1",
    role: "owner",
    org: { id: "org-1", name: "Lagos Audit Collective" },
    isSuspended: false,
  }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  deactivateOrganizationV1OrgsOrgIdDelete: vi.fn(),
  listMembersV1OrgsOrgIdMembersGet: vi.fn(),
  transferOwnershipV1OrgsOrgIdTransferOwnershipPost: vi.fn(),
}));

function ok<T>(data: T) {
  return {
    data,
    error: undefined,
    request: new Request("http://test.local"),
    response: new Response(null, { status: 200 }),
  };
}

function failed(status: number, error: unknown) {
  return {
    data: undefined,
    error,
    request: new Request("http://test.local"),
    response: new Response(null, { status }),
  };
}

const MEMBERS = [
  {
    id: "mem-owner",
    user_id: "user-owner",
    display_name: "Ngozi Okafor",
    email: "ngozi@example.com",
    role: "owner",
    joined_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "mem-admin",
    user_id: "user-admin",
    display_name: "Tunde Bakare",
    email: "tunde@example.com",
    role: "admin",
    joined_at: "2026-02-01T00:00:00Z",
  },
  {
    id: "mem-member",
    user_id: "user-member",
    display_name: "Amaka Eze",
    email: "amaka@example.com",
    role: "member",
    joined_at: "2026-03-01T00:00:00Z",
  },
];

describe("OrganizationDangerZone", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMembersV1OrgsOrgIdMembersGet).mockResolvedValue(
      ok({ members: MEMBERS }) as never,
    );
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, reload: vi.fn() },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("lists the other members as new-owner candidates, excluding the owner", async () => {
    render(<OrganizationDangerZone />);

    const select = await screen.findByLabelText(/new owner/i);
    const labels = Array.from(select.querySelectorAll("option")).map(
      (option) => option.textContent,
    );

    expect(labels).toContain("Tunde Bakare (tunde@example.com)");
    expect(labels).toContain("Amaka Eze (amaka@example.com)");
    expect(labels.join(" ")).not.toMatch(/Ngozi Okafor/);
  });

  it("shows an error line when the member list fails to load", async () => {
    vi.mocked(listMembersV1OrgsOrgIdMembersGet).mockResolvedValue(
      failed(500, { detail: { error_code: "internal_error" } }) as never,
    );

    render(<OrganizationDangerZone />);

    expect(await screen.findByText("described server error")).toBeInTheDocument();
    expect(screen.queryByLabelText(/new owner/i)).toBeNull();
  });

  it("transfers ownership to the chosen member", async () => {
    vi.mocked(transferOwnershipV1OrgsOrgIdTransferOwnershipPost).mockResolvedValue(
      ok(undefined) as never,
    );

    render(<OrganizationDangerZone />);

    const select = await screen.findByLabelText(/new owner/i);
    const submit = screen.getByRole("button", { name: /transfer ownership/i });
    expect(submit).toBeDisabled();

    fireEvent.change(select, { target: { value: "mem-admin" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() =>
      expect(transferOwnershipV1OrgsOrgIdTransferOwnershipPost).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: { new_owner_member_id: "mem-admin" },
        }),
      ),
    );
  });

  it("surfaces a transfer failure through describeGeneratedError", async () => {
    vi.mocked(transferOwnershipV1OrgsOrgIdTransferOwnershipPost).mockResolvedValue(
      failed(422, { detail: { error_code: "step_up_required" } }) as never,
    );

    render(<OrganizationDangerZone />);

    fireEvent.change(await screen.findByLabelText(/new owner/i), {
      target: { value: "mem-member" },
    });
    fireEvent.click(screen.getByRole("button", { name: /transfer ownership/i }));

    expect(await screen.findByText("described server error")).toBeInTheDocument();
    expect(screen.queryByText("step_up_required")).toBeNull();
  });

  it("keeps Deactivate disabled until the confirmation phrase is typed", async () => {
    vi.mocked(deactivateOrganizationV1OrgsOrgIdDelete).mockResolvedValue(
      ok(undefined) as never,
    );

    render(<OrganizationDangerZone />);
    await screen.findByLabelText(/new owner/i);

    fireEvent.click(screen.getByRole("button", { name: /deactivate organization/i }));

    const confirm = screen.getByRole("button", { name: /^deactivate$/i });
    expect(confirm).toBeDisabled();

    const input = screen.getByPlaceholderText("Delete Lagos Audit Collective");
    fireEvent.change(input, { target: { value: "Delete Lagos" } });
    expect(confirm).toBeDisabled();

    fireEvent.change(input, { target: { value: "Delete Lagos Audit Collective" } });
    expect(confirm).toBeEnabled();

    fireEvent.click(confirm);
    await waitFor(() =>
      expect(deactivateOrganizationV1OrgsOrgIdDelete).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1" } }),
      ),
    );
  });
});
