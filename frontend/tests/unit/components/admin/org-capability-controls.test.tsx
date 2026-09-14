/**
 * Behaviour of the generic org capability controls used by the admin
 * organizations directory and the attestor console.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgCapabilityControls } from "@/components/modules/admin/org-capability-controls";
import {
  reinstateOrgContributorCapability,
  revokeOrgOperatorCapability,
  suspendOrgContributorCapability,
} from "@/lib/generated/sdk.gen";

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

const REASON = "Framework artifacts failed the malware scan twice.";

describe("OrgCapabilityControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("only offers the transitions valid for the current status", () => {
    render(
      <OrgCapabilityControls
        capability="operator"
        onChanged={vi.fn()}
        onError={vi.fn()}
        orgId="org-1"
        orgName="Kano Audit Partners"
        status="suspended"
      />,
    );

    expect(screen.getByRole("button", { name: "Suspend" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reinstate" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeEnabled();
  });

  it("suspends the contributor capability with an owner-visible reason", async () => {
    const onChanged = vi.fn();
    vi.mocked(suspendOrgContributorCapability).mockResolvedValue({
      response: { ok: true },
    } as never);

    render(
      <OrgCapabilityControls
        capability="contributor"
        onChanged={onChanged}
        onError={vi.fn()}
        orgId="org-1"
        orgName="Kano Audit Partners"
        status="active"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Suspend" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Suspend contributor capability?");
    // Confirm stays disabled until the reason satisfies the backend rule.
    expect(
      screen.getAllByRole("button", { name: "Suspend" }).at(-1),
    ).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: REASON } });
    fireEvent.click(screen.getAllByRole("button", { name: "Suspend" }).at(-1)!);

    await waitFor(() =>
      expect(vi.mocked(suspendOrgContributorCapability)).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { reason: REASON },
          path: { org_id: "org-1" },
        }),
      ),
    );
    expect(onChanged).toHaveBeenCalledWith("suspended", REASON);
  });

  it("reinstates without a reason and clears the stored one", async () => {
    const onChanged = vi.fn();
    vi.mocked(reinstateOrgContributorCapability).mockResolvedValue({
      response: { ok: true },
    } as never);

    render(
      <OrgCapabilityControls
        capability="contributor"
        onChanged={onChanged}
        onError={vi.fn()}
        orgId="org-1"
        orgName="Kano Audit Partners"
        status="suspended"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reinstate" }));
    expect(screen.queryByLabelText(/Reason/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Reinstate" }).at(-1)!);

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith("active", null));
    expect(vi.mocked(reinstateOrgContributorCapability)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" } }),
    );
  });

  it("reports a refused revoke instead of changing the row", async () => {
    const onChanged = vi.fn();
    const onError = vi.fn();
    vi.mocked(revokeOrgOperatorCapability).mockResolvedValue({
      error: { detail: "nope" },
      response: { ok: false, status: 403 },
    } as never);

    render(
      <OrgCapabilityControls
        capability="operator"
        onChanged={onChanged}
        onError={onError}
        orgId="org-1"
        orgName="Kano Audit Partners"
        status="active"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: REASON } });
    fireEvent.click(screen.getAllByRole("button", { name: "Revoke" }).at(-1)!);

    await waitFor(() => expect(onError).toHaveBeenCalledWith("Request refused."));
    expect(onChanged).not.toHaveBeenCalled();
  });
});
