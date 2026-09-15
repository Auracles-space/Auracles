import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptAttestationReport,
  cancelAttestationRequest,
  createAttestationDispute,
  getAttestation,
  getAttestationFeePayment,
  getAttestationInvoiceV1AttestationsAttestationIdInvoiceGet,
  rateAttestationV1AttestationsAttestationIdRatingPost,
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
  cancelAttestationRequest: vi.fn(),
  createAttestationDispute: vi.fn(),
  getAttestationInvoiceV1AttestationsAttestationIdInvoiceGet: vi.fn(),
  rateAttestationV1AttestationsAttestationIdRatingPost: vi.fn(),
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

/** A submitted-report attestation the requestor can accept or dispute. */
function reportedAttestation() {
  return {
    id: "att-1",
    target_type: "framework",
    target_id: "fw-1",
    target_title: "Governance Playbook",
    requestor_id: "user-1",
    attestor_org_id: "org-1",
    attestor_org_name: "Lagos Assurance",
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
    dispute_window_ends_at: "2026-09-25T00:00:00Z",
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
  };
}

/** Load the detail view in a given status. */
function mockDetail(overrides: Record<string, unknown> = {}) {
  vi.mocked(getAttestation).mockResolvedValue({
    response: { ok: true },
    data: { ...reportedAttestation(), ...overrides },
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AttestationDetail", () => {
  it("renders the brief, report, and status for the request", async () => {
    mockDetail();

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByText("Structures governance decisions."),
    ).toBeInTheDocument();
    expect(screen.getByText("Meets the quality bar.")).toBeInTheDocument();
    expect(screen.getByText("Board oversight.")).toBeInTheDocument();
  });

  it("heads the page with the framework and links the reviewing organization", async () => {
    mockDetail();

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByRole("heading", { name: "Governance Playbook" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Lagos Assurance" }),
    ).toHaveAttribute("href", "/attestors/org-1");
  });

  it("shows the progress track and the next step", async () => {
    mockDetail();

    render(<AttestationDetail attestationId="att-1" />);

    await screen.findByRole("list", { name: "Request progress" });
    expect(
      screen.getByText(
        "Read the report, then accept it or dispute it by 25 Sep 2026.",
      ),
    ).toBeInTheDocument();
  });

  it("accepts the report through the accept action", async () => {
    mockDetail();
    vi.mocked(acceptAttestationReport).mockResolvedValue({
      response: { ok: true },
      data: { ...reportedAttestation(), status: "released" },
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

  it("disputes with an explicit category and evidence", async () => {
    mockDetail();
    vi.mocked(createAttestationDispute).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);

    render(<AttestationDetail attestationId="att-1" />);
    await screen.findByText("Dispute by 25 Sep 2026");

    fireEvent.change(screen.getByLabelText(/Category/i), {
      target: { value: "material_inaccuracy" },
    });
    fireEvent.change(screen.getByLabelText(/What went wrong/i), {
      target: {
        value:
          "The report states the control set was tested, but no evidence is attached anywhere.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Raise dispute/i }));

    await waitFor(() => {
      expect(createAttestationDispute).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({ category: "material_inaccuracy" }),
          path: { attestation_id: "att-1" },
        }),
      );
    });
  });

  it("blocks a dispute until the evidence meets the platform's floor", async () => {
    // The floor is platform config served on the detail, not a client constant.
    mockDetail({ dispute_evidence_min_length: 25 });

    render(<AttestationDetail attestationId="att-1" />);
    await screen.findByText("Dispute by 25 Sep 2026");

    fireEvent.change(screen.getByLabelText(/What went wrong/i), {
      target: { value: "Too short." },
    });

    expect(
      screen.getByRole("button", { name: /Raise dispute/i }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        "Describe what is wrong and point to the evidence (at least 25 characters).",
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/What went wrong/i), {
      target: { value: "Long enough to substantiate it." },
    });
    expect(
      screen.getByRole("button", { name: /Raise dispute/i }),
    ).toBeEnabled();
  });

  it("leaves evidence length to the server when no floor is served", async () => {
    mockDetail({ dispute_evidence_min_length: null });

    render(<AttestationDetail attestationId="att-1" />);
    await screen.findByText("Dispute by 25 Sep 2026");

    fireEvent.change(screen.getByLabelText(/What went wrong/i), {
      target: { value: "Short." },
    });

    expect(
      screen.getByRole("button", { name: /Raise dispute/i }),
    ).toBeEnabled();
    expect(
      screen.getByText("Describe what is wrong and point to the evidence."),
    ).toBeInTheDocument();
  });

  it("resumes payment for a pending-fee request", async () => {
    mockDetail({ status: "pending_fee", summary: null, scope: null });
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
      mockDetail({ status: "pending_fee", summary: null, scope: null });
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

describe("AttestationDetail returning from hosted checkout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("confirms the payment instead of asking to pay again, then shows the funded request", async () => {
    // Paystack sends the payer back before its webhook lands, so the first load
    // still reads pending_fee. Offering "Pay fee" there invites a second charge.
    vi.mocked(getAttestation)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: { ...reportedAttestation(), status: "pending_fee", summary: null, scope: null },
      } as never)
      .mockResolvedValue({
        response: { ok: true },
        data: { ...reportedAttestation(), status: "offered", summary: null, scope: null },
      } as never);

    render(<AttestationDetail attestationId="att-1" returningFromPayment />);

    expect(await screen.findByText(/Confirming your payment/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pay fee/i })).toBeNull();

    await vi.advanceTimersByTimeAsync(3000);

    await waitFor(() =>
      expect(screen.queryByText(/Confirming your payment/i)).toBeNull(),
    );
    expect(getAttestation).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: /Pay fee/i })).toBeNull();
  });

  it("offers payment again with an explanation when confirmation never arrives", async () => {
    mockDetail({ status: "pending_fee", summary: null, scope: null });

    render(<AttestationDetail attestationId="att-1" returningFromPayment />);
    await screen.findByText(/Confirming your payment/i);

    await vi.advanceTimersByTimeAsync(60_000);

    expect(
      await screen.findByText(/haven't received confirmation of your payment yet/i),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Pay fee/i })).toBeInTheDocument();
  });
});

describe("AttestationDetail withdrawal", () => {
  it("withdraws a request that no attestor has accepted yet", async () => {
    mockDetail({
      status: "matching",
      summary: null,
      scope: null,
      attestor_org_id: null,
      attestor_org_name: null,
    });
    vi.mocked(cancelAttestationRequest).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);

    render(<AttestationDetail attestationId="att-1" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Withdraw request" }),
    );

    expect(
      await screen.findByText("Withdraw this request?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your request is cancelled and the fee is refunded to the original payment method.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Yes, withdraw" }));

    await waitFor(() => {
      expect(cancelAttestationRequest).toHaveBeenCalledWith(
        expect.objectContaining({ path: { attestation_id: "att-1" } }),
      );
    });
  });

  it("says nothing is charged yet when withdrawing before payment", async () => {
    mockDetail({
      status: "pending_owner_consent",
      summary: null,
      scope: null,
      escrow_id: null,
      attestor_org_id: null,
      attestor_org_name: null,
    });

    render(<AttestationDetail attestationId="att-1" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Withdraw request" }),
    );

    expect(
      await screen.findByText(
        "Your request is cancelled. Nothing has been charged, so there is nothing to refund.",
      ),
    ).toBeInTheDocument();
  });

  it("explains why an accepted request can no longer be withdrawn", async () => {
    mockDetail({ status: "in_review", summary: null, scope: null });

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByText(
        "An attestor has accepted, so this request can no longer be withdrawn.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Withdraw request" }),
    ).toBeNull();
  });
});

describe("AttestationDetail settled request", () => {
  it("rates the attestor once the request is released", async () => {
    mockDetail({ status: "released" });
    vi.mocked(rateAttestationV1AttestationsAttestationIdRatingPost).mockResolvedValue(
      { response: { ok: true }, data: { stars: 4 } } as never,
    );

    render(<AttestationDetail attestationId="att-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "4 stars" }));
    fireEvent.change(screen.getByLabelText(/Comment/i), {
      target: { value: "Clear and on time." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit rating" }));

    await waitFor(() => {
      expect(
        rateAttestationV1AttestationsAttestationIdRatingPost,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { stars: 4, comment: "Clear and on time." },
          path: { attestation_id: "att-1" },
        }),
      );
    });
    expect(
      await screen.findByText("You have rated this attestation."),
    ).toBeInTheDocument();
  });

  it("treats an already-rated attestation as rated", async () => {
    mockDetail({ status: "closed" });
    vi.mocked(rateAttestationV1AttestationsAttestationIdRatingPost).mockResolvedValue(
      { response: { ok: false, status: 409 }, error: {} } as never,
    );

    render(<AttestationDetail attestationId="att-1" />);

    fireEvent.click(await screen.findByRole("button", { name: "5 stars" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit rating" }));

    expect(
      await screen.findByText("You have rated this attestation."),
    ).toBeInTheDocument();
  });

  it("opens the invoice returned by the invoice endpoint", async () => {
    mockDetail({ status: "released" });
    vi.mocked(
      getAttestationInvoiceV1AttestationsAttestationIdInvoiceGet,
    ).mockResolvedValue({
      data: { download_url: "https://s3.test/invoice.pdf" },
      response: { ok: true, status: 200 },
    } as never);
    const open = vi.spyOn(window, "open").mockReturnValue(null);

    render(<AttestationDetail attestationId="att-1" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Download invoice" }),
    );

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith(
        "https://s3.test/invoice.pdf",
        "_blank",
        "noopener",
      );
    });
    open.mockRestore();
  });

  it("says the invoice is still being prepared on a 202", async () => {
    mockDetail({ status: "released" });
    vi.mocked(
      getAttestationInvoiceV1AttestationsAttestationIdInvoiceGet,
    ).mockResolvedValue({
      response: { ok: true, status: 202, url: "" },
      data: { status: "generating" },
    } as never);

    render(<AttestationDetail attestationId="att-1" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Download invoice" }),
    );

    expect(
      await screen.findByText(
        "The invoice is being prepared. Try again in a moment.",
      ),
    ).toBeInTheDocument();
  });

  it("states the refund on a refunded request", async () => {
    mockDetail({ status: "refunded" });

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByText(
        "The fee was refunded to your original payment method.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Submit rating" }),
    ).toBeNull();
  });

  it("states the withdrawal on a cancelled request", async () => {
    mockDetail({ status: "cancelled" });

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByText(
        "You withdrew this request. Any fee you paid has been refunded.",
      ),
    ).toBeInTheDocument();
  });
});

describe("AttestationDetail dispute", () => {
  it("shows an open dispute with its category and decision date", async () => {
    mockDetail({
      status: "disputed",
      dispute: {
        id: "dis-1",
        status: "open",
        category: "scope_error",
        reason: "The report reviewed the wrong version.",
        outcome: null,
        resolution_notes: null,
        resolution_due_at: "2026-10-02T00:00:00Z",
        resolved_at: null,
        created_at: "2026-09-26T00:00:00Z",
      },
    });

    render(<AttestationDetail attestationId="att-1" />);

    expect(
      await screen.findByRole("heading", { name: "Dispute" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Scope error")).toBeInTheDocument();
    expect(
      screen.getByText("The report reviewed the wrong version."),
    ).toBeInTheDocument();
    expect(screen.getByText("Decision due 2 Oct 2026")).toBeInTheDocument();
  });

  it("shows the outcome and notes once the dispute is decided", async () => {
    mockDetail({
      status: "released",
      dispute: {
        id: "dis-1",
        status: "resolved",
        category: "scope_error",
        reason: "The report reviewed the wrong version.",
        outcome: "rejected",
        resolution_notes: "The correct version was reviewed.",
        resolution_due_at: "2026-10-02T00:00:00Z",
        resolved_at: "2026-10-01T00:00:00Z",
        created_at: "2026-09-26T00:00:00Z",
      },
    });

    render(<AttestationDetail attestationId="att-1" />);

    expect(await screen.findByText("Rejected")).toBeInTheDocument();
    expect(
      screen.getByText("The correct version was reviewed."),
    ).toBeInTheDocument();
  });
});
