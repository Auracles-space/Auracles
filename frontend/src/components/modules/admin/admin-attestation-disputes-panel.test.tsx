import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  listAdminAttestationDisputes,
  resolveAttestationDispute,
} from "@/lib/generated/sdk.gen";
import { AdminAttestationDisputesPanel } from "./admin-attestation-disputes-panel";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminAttestationDisputes: vi.fn(),
  resolveAttestationDispute: vi.fn(),
}));

/** One open dispute as the queue endpoint returns it. */
function openDispute(overrides: Record<string, unknown> = {}) {
  return {
    id: "dsp-1",
    attestation_id: "att-1",
    category: "material_inaccuracy",
    reason: "The report cites a control we never implemented.",
    status: "open",
    outcome: null,
    is_complex: false,
    resolution_due_at: "2026-09-20T00:00:00Z",
    escalated_at: null,
    resolved_at: null,
    created_at: "2026-09-10T00:00:00Z",
    attestation_status: "disputed",
    review_type: "compliance",
    fee_amount: "500.00",
    currency: "NGN",
    attestor_org_id: "org-1",
    attestor_org_name: "Lagos Assurance Partners",
    ...overrides,
  };
}

describe("AdminAttestationDisputesPanel", () => {
  it("lists each open dispute with the context needed to judge it", async () => {
    vi.mocked(listAdminAttestationDisputes).mockResolvedValue({
      response: { ok: true },
      data: { disputes: [openDispute()] },
    } as never);

    render(<AdminAttestationDisputesPanel />);

    expect(
      await screen.findByText(/The report cites a control we never implemented\./),
    ).toBeInTheDocument();
    expect(screen.getByText("Lagos Assurance Partners")).toBeInTheDocument();
    expect(screen.getByText(/material inaccuracy/i)).toBeInTheDocument();
  });

  it("resolves the selected dispute with the revision verdict", async () => {
    vi.mocked(listAdminAttestationDisputes).mockResolvedValue({
      response: { ok: true },
      data: { disputes: [openDispute()] },
    } as never);
    vi.mocked(resolveAttestationDispute).mockResolvedValue({
      response: { ok: true },
      data: { id: "dsp-1", outcome: "upheld_revise" },
    } as never);

    render(<AdminAttestationDisputesPanel />);

    // Exact name: the "Resolved" status filter is also a button.
    fireEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    fireEvent.click(
      screen.getByRole("radio", { name: /require a revision/i }),
    );
    fireEvent.change(screen.getByLabelText(/Resolution notes/i), {
      target: { value: "Control 4.2 was never in scope; revise and resubmit." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Confirm verdict/i }));

    await waitFor(() => {
      expect(resolveAttestationDispute).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { dispute_id: "dsp-1" },
          body: expect.objectContaining({ outcome: "upheld_revise" }),
        }),
      );
    });
  });

  it("offers only verdicts the API implements, and never a split", async () => {
    // Regression guard. The previous control offered "Split Escrow Funds" with
    // two amount fields; the amounts went nowhere and the request fell through
    // to `rejected`, which releases the whole escrow to the Attestor. Any
    // option the API cannot honour is a silent payout, so the set is pinned.
    vi.mocked(listAdminAttestationDisputes).mockResolvedValue({
      response: { ok: true },
      data: { disputes: [openDispute()] },
    } as never);

    render(<AdminAttestationDisputesPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Resolve" }));

    const verdicts = screen
      .getAllByRole("radio")
      .map((radio) => (radio as HTMLInputElement).value);
    expect(verdicts).toEqual(["rejected", "upheld_refund", "upheld_revise"]);
    expect(screen.queryByText(/split/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/amount/i)).not.toBeInTheDocument();
  });

  it("does not carry one dispute's verdict over to another", async () => {
    // The form is shared across rows. Carrying state over would submit the
    // first dispute's verdict and notes against the second one's escrow.
    vi.mocked(listAdminAttestationDisputes).mockResolvedValue({
      response: { ok: true },
      data: {
        disputes: [
          openDispute(),
          openDispute({ id: "dsp-2", attestor_org_id: "org-2" }),
        ],
      },
    } as never);

    render(<AdminAttestationDisputesPanel />);

    const [firstResolve, secondResolve] = await screen.findAllByRole("button", {
      name: "Resolve",
    });
    fireEvent.click(firstResolve);
    fireEvent.click(screen.getByRole("radio", { name: /Reject the dispute/i }));
    fireEvent.change(screen.getByLabelText(/Resolution notes/i), {
      target: { value: "Notes typed against the first dispute." },
    });

    fireEvent.click(secondResolve);

    expect(screen.getByLabelText(/Resolution notes/i)).toHaveValue("");
    expect(
      screen.getByRole("radio", { name: /Reject the dispute/i }),
    ).not.toBeChecked();
  });

  it("keeps the verdict disabled until a verdict and notes are supplied", async () => {
    vi.mocked(listAdminAttestationDisputes).mockResolvedValue({
      response: { ok: true },
      data: { disputes: [openDispute()] },
    } as never);

    render(<AdminAttestationDisputesPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Resolve" }));
    const confirm = screen.getByRole("button", { name: /Confirm verdict/i });
    expect(confirm).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: /refund the requester/i }));
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Resolution notes/i), {
      target: { value: "Report withdrawn; refund in full." },
    });
    expect(confirm).toBeEnabled();
    expect(screen.queryByLabelText(/2FA code/i)).not.toBeInTheDocument();
  });
});
