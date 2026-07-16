import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  acceptAttestationReport,
  getAttestation,
} from "@/lib/generated/sdk.gen";
import { AttestationDetail } from "./attestation-detail";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAttestation: vi.fn(),
  acceptAttestationReport: vi.fn(),
  createAttestationDispute: vi.fn(),
}));

/** A submitted-report attestation the requestor can accept or dispute. */
function reportedAttestation() {
  return {
    id: "att-1",
    target_type: "framework",
    target_id: "fw-1",
    requestor_id: "user-1",
    attestor_org_id: "org-1",
    status: "report_submitted",
    outcome: null,
    review_type: "quality",
    brief: {
      what_it_does: "Structures governance decisions.",
      use_case: "Board oversight.",
      jurisdiction: "global",
      focus_areas: "Controls.",
      desired_outcome: "Sign-off.",
    },
    requested_specializations: [],
    requested_jurisdictions: [],
    summary: "Meets the quality bar.",
    scope: "Reviewed all artifacts.",
    fee_amount: "500.00",
    currency: "USD",
    escrow_id: "esc-1",
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
  };
}

describe("AttestationDetail", () => {
  it("renders the brief, report, and status for the request", async () => {
    vi.mocked(getAttestation).mockResolvedValue({
      response: { ok: true },
      data: reportedAttestation(),
    } as never);

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByText("Structures governance decisions."),
    ).toBeInTheDocument();
    expect(screen.getByText("Meets the quality bar.")).toBeInTheDocument();
    expect(screen.getByText("Board oversight.")).toBeInTheDocument();
  });

  it("accepts the report through the accept action", async () => {
    vi.mocked(getAttestation).mockResolvedValue({
      response: { ok: true },
      data: reportedAttestation(),
    } as never);
    vi.mocked(acceptAttestationReport).mockResolvedValue({
      response: { ok: true },
      data: { ...reportedAttestation(), status: "accepted" },
    } as never);

    render(<AttestationDetail attestationId="att-1" />);
    await screen.findByText("Meets the quality bar.");

    fireEvent.click(screen.getByRole("button", { name: /Accept report/i }));

    await waitFor(() => {
      expect(acceptAttestationReport).toHaveBeenCalledWith(
        expect.objectContaining({ path: { attestation_id: "att-1" } }),
      );
    });
  });
});
