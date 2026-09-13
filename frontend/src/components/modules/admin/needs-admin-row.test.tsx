import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  adminAssignAttestation,
  adminRefundAttestation,
} from "@/lib/generated/sdk.gen";
import { NeedsAdminRow } from "./needs-admin-row";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminAssignAttestation: vi.fn(),
  adminRefundAttestation: vi.fn(),
}));

const attestation = {
  id: "att-1",
  target_type: "framework",
  target_id: "fw-1",
  requestor_id: "user-1",
  attestor_org_id: null,
  status: "needs_admin",
  outcome: null,
  review_type: "quality",
  requested_specializations: [],
  requested_jurisdictions: [],
  fee_amount: "500.00",
  currency: "USD",
  escrow_id: "esc-1",
  created_at: "2026-07-16T00:00:00Z",
  updated_at: "2026-07-16T00:00:00Z",
} as never;

const orgs = [{ org_id: "org-1", name: "Acme Advisory" }] as never;

/** Fill the row's reason field with a valid value. */
function fillReason() {
  fireEvent.change(screen.getByPlaceholderText("Reason for this action"), {
    target: { value: "Manual dispatch." },
  });
}

describe("NeedsAdminRow", () => {
  it("assigns to the picked org with no reviewing member", async () => {
    vi.mocked(adminAssignAttestation).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);
    const onResolved = vi.fn();

    render(
      <NeedsAdminRow
        attestation={attestation}
        attestorOrgs={orgs}
        onResolved={onResolved}
      />,
    );

    fillReason();
    fireEvent.change(screen.getByLabelText(/Attestor org/i), {
      target: { value: "org-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Assign to org/i }));

    await waitFor(() => {
      expect(adminAssignAttestation).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1" },
          body: expect.objectContaining({
            attestor_org_id: "org-1",
            reason: "Manual dispatch.",
          }),
        }),
      );
    });
    const body = vi.mocked(adminAssignAttestation).mock.calls[0][0].body;
    expect(body).not.toHaveProperty("reviewing_member_id");
    expect(body).not.toHaveProperty("totp_code");
    expect(onResolved).toHaveBeenCalledWith("att-1");
  });

  it("keeps Assign disabled until an org is picked, but allows Refund", async () => {
    render(
      <NeedsAdminRow
        attestation={attestation}
        attestorOrgs={orgs}
        onResolved={vi.fn()}
      />,
    );

    fillReason();

    // Org not yet picked: assign disabled, refund enabled.
    expect(
      screen.getByRole("button", { name: /Assign to org/i }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: /Refund/i })).toBeEnabled();
  });

  it("refunds the fee", async () => {
    vi.mocked(adminRefundAttestation).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);
    const onResolved = vi.fn();

    render(
      <NeedsAdminRow
        attestation={attestation}
        attestorOrgs={orgs}
        onResolved={onResolved}
      />,
    );

    fillReason();
    fireEvent.click(screen.getByRole("button", { name: /Refund/i }));

    await waitFor(() => {
      expect(adminRefundAttestation).toHaveBeenCalledWith(
        expect.objectContaining({ path: { attestation_id: "att-1" } }),
      );
    });
    expect(onResolved).toHaveBeenCalledWith("att-1");
  });
});

describe("NeedsAdminRow with no active attestor orgs", () => {
  it("explains the empty picker instead of showing a blank dropdown", () => {
    // A request reaches needs_admin precisely because matching found nobody.
    // An empty, unexplained dropdown reads as a broken page rather than as
    // "no organization has completed attestor approval yet".
    render(
      <NeedsAdminRow
        attestation={attestation}
        attestorOrgs={[] as never}
        onResolved={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/No approved attestor organizations/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Attestor org/i)).toBeNull();
    // Refund stays available: it is the only action left to take.
    expect(screen.getByRole("button", { name: /Refund/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Assign to org/i })).toBeNull();
  });
});
