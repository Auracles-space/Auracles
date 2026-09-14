/**
 * Behaviour of the admin dialog that shows one organization's capabilities
 * with their stored reasons and lets an admin change each one.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgCapabilitiesDialog } from "@/components/modules/admin/org-capabilities-dialog";
import { suspendOrgOperatorCapability } from "@/lib/generated/sdk.gen";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  suspendOrgContributorCapability: vi.fn(),
  reinstateOrgContributorCapability: vi.fn(),
  revokeOrgContributorCapability: vi.fn(),
  suspendOrgOperatorCapability: vi.fn(),
  reinstateOrgOperatorCapability: vi.fn(),
  revokeOrgOperatorCapability: vi.fn(),
  suspendOrgAttestorCapability: vi.fn(),
  reinstateOrgAttestorCapability: vi.fn(),
  revokeOrgAttestorCapability: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "Request refused.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer admin" }),
}));

const REASON = "Two chargebacks on framework purchases this month.";

function org(overrides: Partial<AdminOrgResponse> = {}): AdminOrgResponse {
  return {
    id: "org-1",
    slug: "kano-audit",
    name: "Kano Audit Partners",
    country: "NG",
    member_count: 4,
    capabilities: { contributor: "suspended", operator: "active" },
    capability_reasons: { contributor: "Malware in two uploaded artifacts." },
    kyb_status: "verified",
    created_at: "2026-09-01T09:00:00Z",
    ...overrides,
  } as AdminOrgResponse;
}

describe("OrgCapabilitiesDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists every capability with its status and stored reason", () => {
    render(<OrgCapabilitiesDialog onChanged={vi.fn()} onClose={vi.fn()} org={org()} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Kano Audit Partners");
    expect(screen.getByRole("heading", { name: "Contributor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Operator" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Attestor" })).toBeInTheDocument();
    expect(screen.getByText("Suspended")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Not active")).toBeInTheDocument();
    expect(screen.getByText("Malware in two uploaded artifacts.")).toBeInTheDocument();
  });

  it("offers no controls for a capability the org never activated", () => {
    render(
      <OrgCapabilitiesDialog
        onChanged={vi.fn()}
        onClose={vi.fn()}
        org={org({ capabilities: {}, capability_reasons: {} })}
      />,
    );

    expect(screen.queryByRole("button", { name: "Suspend" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Not active")).toHaveLength(3);
  });

  it("reports a capability change with the reason so the directory row updates", async () => {
    const onChanged = vi.fn();
    vi.mocked(suspendOrgOperatorCapability).mockResolvedValue({
      response: { ok: true },
    } as never);

    render(<OrgCapabilitiesDialog onChanged={onChanged} onClose={vi.fn()} org={org()} />);

    // Contributor is suspended, so the only enabled Suspend belongs to operator.
    const suspend = screen
      .getAllByRole("button", { name: "Suspend" })
      .find((button) => !(button as HTMLButtonElement).disabled)!;
    fireEvent.click(suspend);
    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: REASON } });
    fireEvent.click(screen.getAllByRole("button", { name: "Suspend" }).at(-1)!);

    await waitFor(() =>
      expect(onChanged).toHaveBeenCalledWith("operator", "suspended", REASON),
    );
    expect(vi.mocked(suspendOrgOperatorCapability)).toHaveBeenCalledWith(
      expect.objectContaining({ body: { reason: REASON }, path: { org_id: "org-1" } }),
    );
  });

  it("shows a refused change inside the dialog", async () => {
    vi.mocked(suspendOrgOperatorCapability).mockResolvedValue({
      error: { detail: "step up" },
      response: { ok: false, status: 403 },
    } as never);

    render(<OrgCapabilitiesDialog onChanged={vi.fn()} onClose={vi.fn()} org={org()} />);

    const suspend = screen
      .getAllByRole("button", { name: "Suspend" })
      .find((button) => !(button as HTMLButtonElement).disabled)!;
    fireEvent.click(suspend);
    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: REASON } });
    fireEvent.click(screen.getAllByRole("button", { name: "Suspend" }).at(-1)!);

    expect(await screen.findByText("Request refused.")).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<OrgCapabilitiesDialog onChanged={vi.fn()} onClose={onClose} org={org()} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });
});
