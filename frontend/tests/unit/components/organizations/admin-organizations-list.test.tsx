/**
 * Unit coverage for the admin organization directory.
 *
 * Verifies the suspend confirm dialog collects a required, owner-visible
 * reason before the request fires, that reinstate stays body-less, and that
 * each row names its capabilities and opens a per-capability dialog whose
 * changes update the row without a refetch. Also covers the responsive
 * layout (a card per organization below `md`, the table above), status and
 * KYB pills, suspension and closure context, admin reactivation, and
 * described errors.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminOrganizationsList } from "@/components/modules/organizations/admin-organizations-list";
import { configureBrowserClient } from "@/lib/auth/form-client";
import {
  adminListOrgsV1AdminOrgsGet,
  adminReactivateOrgV1AdminOrgsOrgIdReactivatePost,
  adminReinstateOrgV1AdminOrgsOrgIdReinstatePost,
  adminSuspendOrgV1AdminOrgsOrgIdSuspendPost,
  suspendOrgContributorCapability,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(
    (error: { detail?: string } | undefined) =>
      error?.detail ?? "The request could not be completed.",
  ),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminListOrgsV1AdminOrgsGet: vi.fn(),
  adminReactivateOrgV1AdminOrgsOrgIdReactivatePost: vi.fn(),
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

const failed = (status: number, detail: string) => ({
  data: undefined,
  error: { detail },
  request: new Request("http://t"),
  response: new Response(null, { status }),
});

/** Find the table row (md+ layout) for an organization by name. */
async function tableRow(name: string) {
  const table = await screen.findByRole("table");
  return within(table).getByText(name).closest("tr") as HTMLElement;
}

/** Find the phone-width card for an organization by name. */
async function card(name: string) {
  const list = await screen.findByRole("list", { name: "Organizations" });
  return within(list)
    .getAllByRole("listitem")
    .find((item) => within(item).queryByText(name)) as HTMLElement;
}

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
    vi.mocked(adminReactivateOrgV1AdminOrgsOrgIdReactivatePost).mockReset();
    vi.mocked(configureBrowserClient).mockClear();

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
            kyb_status: "verified",
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
            kyb_status: "pending",
            suspended_at: "2026-09-10T00:00:00Z",
            suspension_reason: "Repeated licence resale complaints",
            deactivated_at: null,
          },
          {
            id: "org-closed",
            name: "Closed Ltd",
            slug: "closed-ltd",
            country: "GB",
            member_count: 2,
            capabilities: {},
            created_at: "2026-09-01T00:00:00Z",
            kyb_status: "rejected",
            suspended_at: null,
            deactivated_at: "2026-09-12T00:00:00Z",
            deactivation_reason: "Owner wound the business down",
          },
        ],
        page: 1,
        page_size: 10,
        total: 3,
      }),
    );
    vi.mocked(adminSuspendOrgV1AdminOrgsOrgIdSuspendPost).mockResolvedValue(ok(undefined));
    vi.mocked(adminReinstateOrgV1AdminOrgsOrgIdReinstatePost).mockResolvedValue(ok(undefined));
  });

  it("keeps Suspend disabled until a reason of at least 5 characters is typed, then sends it", async () => {
    render(<AdminOrganizationsList />);
    const row = await tableRow("Active Ltd");

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
    const row = await tableRow("Paused Ltd");

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
    const row = await tableRow("Active Ltd");

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

    const row = await tableRow("Active Ltd");
    expect(within(row).getByText("Contributor active")).toBeInTheDocument();
    expect(within(row).getByText("Operator suspended")).toBeInTheDocument();
  });

  it("opens the capabilities dialog for a row and updates the row after a change", async () => {
    vi.mocked(suspendOrgContributorCapability).mockResolvedValue(ok(undefined));

    render(<AdminOrganizationsList />);
    const row = await tableRow("Active Ltd");
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
  it("renders every organization as a card for phone widths alongside the md+ table", async () => {
    render(<AdminOrganizationsList />);

    const list = await screen.findByRole("list", { name: "Organizations" });
    expect(list.className).toContain("md:hidden");
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("table").parentElement?.className).toContain("hidden md:block");

    const active = await card("Active Ltd");
    expect(within(active).getByText("@active-ltd")).toBeInTheDocument();
    expect(within(active).getByText(/NG/)).toBeInTheDocument();
    expect(within(active).getByText(/3 members/)).toBeInTheDocument();
    expect(within(active).getByText("Contributor active")).toBeInTheDocument();
    expect(within(active).getByRole("button", { name: "Capabilities" })).toBeInTheDocument();
    expect(within(active).getByRole("button", { name: "Suspend" })).toBeInTheDocument();
  });

  it("shows status and KYB pills for each organization", async () => {
    render(<AdminOrganizationsList />);

    const active = await card("Active Ltd");
    expect(within(active).getByText("Active")).toBeInTheDocument();
    expect(within(active).getByText("Verified")).toBeInTheDocument();

    const paused = await card("Paused Ltd");
    expect(within(paused).getByText("Suspended")).toBeInTheDocument();
    expect(within(paused).getByText("In review")).toBeInTheDocument();

    const closed = await card("Closed Ltd");
    expect(within(closed).getByText("Deactivated")).toBeInTheDocument();
    expect(within(closed).getByText("Needs changes")).toBeInTheDocument();

    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "KYB" })).toBeInTheDocument();
    expect(within(await tableRow("Paused Ltd")).getByText("In review")).toBeInTheDocument();
  });

  it("labels an organization that never submitted KYB as Not verified", async () => {
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue(
      ok({
        orgs: [
          {
            id: "org-new",
            name: "New Ltd",
            slug: "new-ltd",
            country: "NG",
            member_count: 1,
            capabilities: {},
            created_at: "2026-09-13T00:00:00Z",
            kyb_status: "unverified",
            suspended_at: null,
            deactivated_at: null,
          },
        ],
        page: 1,
        page_size: 10,
        total: 1,
      }) as never,
    );
    render(<AdminOrganizationsList />);

    expect(within(await card("New Ltd")).getByText("Not verified")).toBeInTheDocument();
    expect(within(await tableRow("New Ltd")).getByText("Not verified")).toBeInTheDocument();
  });

  it("shows when and why an organization was suspended or closed", async () => {
    render(<AdminOrganizationsList />);

    const paused = await tableRow("Paused Ltd");
    expect(within(paused).getByText("Suspended 10 Sep 2026")).toBeInTheDocument();
    expect(within(paused).getByText("Repeated licence resale complaints")).toBeInTheDocument();

    const closed = await card("Closed Ltd");
    expect(within(closed).getByText("Closed 12 Sep 2026")).toBeInTheDocument();
    expect(within(closed).getByText("Owner wound the business down")).toBeInTheDocument();
  });

  it("keeps Capabilities and Suspend disabled on a closed organization", async () => {
    render(<AdminOrganizationsList />);

    const closed = await tableRow("Closed Ltd");
    expect(within(closed).getByRole("button", { name: "Capabilities" })).toBeDisabled();
    expect(within(closed).getByRole("button", { name: "Suspend" })).toBeDisabled();
    expect(within(closed).getByRole("button", { name: "Reactivate" })).toBeEnabled();
    expect(
      within(await tableRow("Active Ltd")).queryByRole("button", { name: "Reactivate" }),
    ).not.toBeInTheDocument();
  });

  it("reactivates a closed organization after confirmation and reloads the page", async () => {
    vi.mocked(adminReactivateOrgV1AdminOrgsOrgIdReactivatePost).mockResolvedValue(ok(undefined));
    render(<AdminOrganizationsList />);

    fireEvent.click(
      within(await card("Closed Ltd")).getByRole("button", { name: "Reactivate" }),
    );
    expect(
      within(screen.getByRole("dialog")).getByText(
        "Reopen Closed Ltd? Members regain access; the owner is notified.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(dialogConfirm("Reactivate"));

    await waitFor(() =>
      expect(adminReactivateOrgV1AdminOrgsOrgIdReactivatePost).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer admin-token" },
        path: { org_id: "org-closed" },
      }),
    );
    expect(configureBrowserClient).toHaveBeenCalled();
    await waitFor(() => expect(adminListOrgsV1AdminOrgsGet).toHaveBeenCalledTimes(2));
    expect(vi.mocked(adminListOrgsV1AdminOrgsGet).mock.calls[1][0]).toEqual(
      expect.objectContaining({ query: expect.objectContaining({ page: 1 }) }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows the described error inside the dialog when reactivation fails", async () => {
    vi.mocked(adminReactivateOrgV1AdminOrgsOrgIdReactivatePost).mockResolvedValue(
      failed(409, "Settle pending payouts before reopening."),
    );
    render(<AdminOrganizationsList />);

    fireEvent.click(
      within(await tableRow("Closed Ltd")).getByRole("button", { name: "Reactivate" }),
    );
    fireEvent.click(dialogConfirm("Reactivate"));

    expect(
      await within(screen.getByRole("dialog")).findByText(
        "Settle pending payouts before reopening.",
      ),
    ).toBeInTheDocument();
    expect(adminListOrgsV1AdminOrgsGet).toHaveBeenCalledTimes(1);
  });

  it("shows the described error when the directory fails to load", async () => {
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue(
      failed(403, "Admin role required.") as never,
    );
    render(<AdminOrganizationsList />);

    expect(await screen.findByText("Admin role required.")).toBeInTheDocument();
    expect(screen.queryByText("Failed to load organizations.")).not.toBeInTheDocument();
  });
});
