/**
 * Unit coverage for the admin organization directory.
 *
 * Verifies the suspend confirm dialog collects a required, owner-visible
 * reason before the request fires, that reinstate stays body-less, and that
 * each row names its capabilities and opens a per-capability dialog whose
 * changes update the row without a refetch.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminOrganizationsList } from "@/components/modules/organizations/admin-organizations-list";
import {
  adminListOrgsV1AdminOrgsGet,
  adminReinstateOrgV1AdminOrgsOrgIdReinstatePost,
  adminSuspendOrgV1AdminOrgsOrgIdSuspendPost,
  suspendOrgContributorCapability,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminListOrgsV1AdminOrgsGet: vi.fn(),
  adminReinstateOrgV1AdminOrgsOrgIdReinstatePost: vi.fn(),
  adminSuspendOrgV1AdminOrgsOrgIdSuspendPost: vi.fn(),
  suspendOrgContributorCapability: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

/** Find the confirm button inside the open dialog (it shares its label with the row trigger). */
function dialogConfirm(label: string) {
  const dialog = screen.getByRole("dialog");
  return within(dialog).getByRole("button", { name: label });
}

describe("AdminOrganizationsList", () => {
  beforeEach(() => {
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockReset();
    vi.mocked(adminSuspendOrgV1AdminOrgsOrgIdSuspendPost).mockReset();
    vi.mocked(adminReinstateOrgV1AdminOrgsOrgIdReinstatePost).mockReset();

    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue(
      ok({
        orgs: [
          {
            id: "org-active",
            name: "Active Ltd",
            slug: "active-ltd",
            country: "NG",
            member_count: 3,
            capabilities: { contributor: "active", operator: "suspended" },
            capability_reasons: { operator: "Two chargebacks this month." },
            created_at: "2026-09-01T00:00:00Z",
            suspended_at: null,
            deactivated_at: null,
          },
          {
            id: "org-suspended",
            name: "Paused Ltd",
            slug: "paused-ltd",
            country: "NG",
            member_count: 1,
            capabilities: {},
            created_at: "2026-09-01T00:00:00Z",
            suspended_at: "2026-09-10T00:00:00Z",
            deactivated_at: null,
          },
        ],
        page: 1,
        page_size: 10,
        total: 2,
      }),
    );
    vi.mocked(adminSuspendOrgV1AdminOrgsOrgIdSuspendPost).mockResolvedValue(ok(undefined));
    vi.mocked(adminReinstateOrgV1AdminOrgsOrgIdReinstatePost).mockResolvedValue(ok(undefined));
  });

  it("keeps Suspend disabled until a reason of at least 5 characters is typed, then sends it", async () => {
    render(<AdminOrganizationsList />);
    const row = (await screen.findByText("Active Ltd")).closest("tr") as HTMLElement;

    fireEvent.click(within(row).getByRole("button", { name: "Suspend" }));

    const reason = await screen.findByLabelText(/reason \(shown to the organization's owner\)/i);
    expect(screen.getByText(/5 to 500 characters/i)).toBeInTheDocument();
    expect(dialogConfirm("Suspend")).toBeDisabled();

    fireEvent.change(reason, { target: { value: "  no  " } });
    expect(dialogConfirm("Suspend")).toBeDisabled();

    fireEvent.change(reason, { target: { value: "Repeated licence resale complaints" } });
    expect(dialogConfirm("Suspend")).toBeEnabled();

    fireEvent.click(dialogConfirm("Suspend"));

    await waitFor(() =>
      expect(adminSuspendOrgV1AdminOrgsOrgIdSuspendPost).toHaveBeenCalledWith({
        body: { reason: "Repeated licence resale complaints" },
        headers: { Authorization: "Bearer admin-token" },
        path: { org_id: "org-active" },
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("reinstates without a reason body", async () => {
    render(<AdminOrganizationsList />);
    const row = (await screen.findByText("Paused Ltd")).closest("tr") as HTMLElement;

    fireEvent.click(within(row).getByRole("button", { name: "Reinstate" }));

    expect(screen.queryByLabelText(/reason/i)).not.toBeInTheDocument();
    expect(dialogConfirm("Reinstate")).toBeEnabled();
    fireEvent.click(dialogConfirm("Reinstate"));

    await waitFor(() =>
      expect(adminReinstateOrgV1AdminOrgsOrgIdReinstatePost).toHaveBeenCalledTimes(1),
    );
    const call = vi.mocked(adminReinstateOrgV1AdminOrgsOrgIdReinstatePost).mock.calls[0][0];
    expect(call).not.toHaveProperty("body");
    expect(call.path).toEqual({ org_id: "org-suspended" });
  });

  it("clears a half-typed reason when the dialog is dismissed", async () => {
    render(<AdminOrganizationsList />);
    const row = (await screen.findByText("Active Ltd")).closest("tr") as HTMLElement;

    fireEvent.click(within(row).getByRole("button", { name: "Suspend" }));
    fireEvent.change(await screen.findByLabelText(/reason/i), {
      target: { value: "Draft reason text" },
    });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));

    fireEvent.click(within(row).getByRole("button", { name: "Suspend" }));
    expect(await screen.findByLabelText(/reason/i)).toHaveValue("");
    expect(dialogConfirm("Suspend")).toBeDisabled();
  });

  it("names each capability and its status on the row", async () => {
    render(<AdminOrganizationsList />);

    expect(await screen.findByText("Contributor active")).toBeInTheDocument();
    expect(screen.getByText("Operator suspended")).toBeInTheDocument();
  });

  it("opens the capabilities dialog for a row and updates the row after a change", async () => {
    vi.mocked(suspendOrgContributorCapability).mockResolvedValue(ok(undefined));

    render(<AdminOrganizationsList />);
    const row = (await screen.findByText("Active Ltd")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Capabilities" }));

    const dialog = screen.getByRole("dialog", { name: "Active Ltd" });
    expect(within(dialog).getByText("Two chargebacks this month.")).toBeInTheDocument();

    // Contributor is active, so its Suspend is the only enabled one.
    const suspend = within(dialog)
      .getAllByRole("button", { name: "Suspend" })
      .find((button) => !(button as HTMLButtonElement).disabled)!;
    fireEvent.click(suspend);
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Framework artifacts failed the malware scan twice." },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Suspend" }).at(-1)!);

    await waitFor(() =>
      expect(
        within(dialog).getByText("Framework artifacts failed the malware scan twice."),
      ).toBeInTheDocument(),
    );
    expect(suspendOrgContributorCapability).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { reason: "Framework artifacts failed the malware scan twice." },
        path: { org_id: "org-active" },
      }),
    );
    // The directory row reflects the change without a refetch.
    expect(adminListOrgsV1AdminOrgsGet).toHaveBeenCalledTimes(1);
    expect(within(row).getByText("Contributor suspended")).toBeInTheDocument();
  });
});
