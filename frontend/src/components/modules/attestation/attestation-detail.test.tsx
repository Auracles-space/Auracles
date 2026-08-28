import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  acceptAttestationReport,
  getAttestation,
  getAttestationFeePayment,
} from "@/lib/generated/sdk.gen";
import { AttestationDetail } from "./attestation-detail";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAttestation: vi.fn(),
  getAttestationFeePayment: vi.fn(),
  acceptAttestationReport: vi.fn(),
  createAttestationDispute: vi.fn(),
  // The requestor clarifications panel loads on mount; without this export the
  // mocked module rejects with "no export defined" as an unhandled rejection.
  listAttestationClarifications: vi.fn(() =>
    Promise.resolve({ data: [], error: undefined, response: { ok: true } }),
  ),
}));

// Stub the Stripe-backed funding panel so tests avoid mounting Stripe Elements.
vi.mock("./attestation-funding-panel", () => ({
  AttestationFundingPanel: ({ attestationId }: { attestationId: string }) => (
    <div data-testid="funding-panel">Pay fee for {attestationId}</div>
  ),
}));

/** A pending-fee attestation the requestor still needs to pay. */
function pendingFeeAttestation() {
  return { ...reportedAttestation(), status: "pending_fee", summary: null, scope: null };
}

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

  it("resumes payment for a pending-fee request", async () => {
    vi.mocked(getAttestation).mockResolvedValue({
      response: { ok: true },
      data: pendingFeeAttestation(),
    } as never);
    vi.mocked(getAttestationFeePayment).mockResolvedValue({
      response: { ok: true },
      data: {
        id: "att-1",
        transaction_id: "txn-1",
        provider: "stripe",
        client_secret: "pi_secret_test",
      },
    } as never);

    render(<AttestationDetail attestationId="att-1" />);
    const payButton = await screen.findByRole("button", { name: /Pay fee/i });
    fireEvent.click(payButton);

    expect(await screen.findByTestId("funding-panel")).toHaveTextContent(
      "att-1",
    );
    expect(getAttestationFeePayment).toHaveBeenCalledWith(
      expect.objectContaining({ path: { attestation_id: "att-1" } }),
    );
  });

  it("redirects to Paystack hosted checkout when resuming a Paystack fee", async () => {
    // The stored transaction's rail decides: a Paystack fee resumes as a
    // fresh hosted checkout, so the browser navigates instead of opening the
    // in-page Stripe panel.
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign: vi.fn(), origin: "http://localhost:3000" },
    });
    try {
      vi.mocked(getAttestation).mockResolvedValue({
        response: { ok: true },
        data: pendingFeeAttestation(),
      } as never);
      vi.mocked(getAttestationFeePayment).mockResolvedValue({
        response: { ok: true },
        data: {
          id: "att-1",
          transaction_id: "txn-1",
          provider: "paystack",
          client_secret: null,
          authorization_url: "https://checkout.paystack.com/attestation_resume",
        },
      } as never);

      render(<AttestationDetail attestationId="att-1" />);
      const payButton = await screen.findByRole("button", { name: /Pay fee/i });
      fireEvent.click(payButton);

      await waitFor(() => {
        expect(window.location.assign).toHaveBeenCalledWith(
          "https://checkout.paystack.com/attestation_resume",
        );
      });
      expect(screen.queryByTestId("funding-panel")).toBeNull();
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });
});
