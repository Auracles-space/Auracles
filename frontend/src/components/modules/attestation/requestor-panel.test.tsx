import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getExploreFrameworkDetail,
  listAttestations,
  requestAttestation,
} from "@/lib/generated/sdk.gen";
import { RequestorPanel } from "./requestor-panel";

const { searchParams } = vi.hoisted(() => ({
  searchParams: { value: null as string | null },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => searchParams.value }),
}));

beforeEach(() => {
  searchParams.value = null;
  vi.mocked(getExploreFrameworkDetail).mockClear();
});

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

// Stub the Stripe-backed funding panel so tests avoid mounting Stripe Elements.
vi.mock("./attestation-funding-panel", () => ({
  AttestationFundingPanel: ({ attestationId }: { attestationId: string }) => (
    <div data-testid="funding-panel">Pay fee for {attestationId}</div>
  ),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptAttestationReport: vi.fn(),
  cancelAttestationRequest: vi.fn(),
  createAttestationDispute: vi.fn(),
  listAttestations: vi.fn(async () => ({
    response: { ok: true },
    data: { attestations: [] },
  })),
  listContributorFrameworks: vi.fn(async () => ({
    response: { ok: true },
    data: [
      {
        id: "11111111-1111-1111-1111-111111111111",
        title: "Governance Playbook",
        version: "1.0.0",
        status: "published",
        category: "governance",
        price: "0",
        currency: "USD",
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-01T00:00:00Z",
      },
      {
        id: "22222222-2222-2222-2222-222222222222",
        title: "Risk Register Template",
        version: "1.0.0",
        status: "draft",
        category: "risk",
        price: "0",
        currency: "USD",
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-01T00:00:00Z",
      },
    ],
  })),
  requestAttestation: vi.fn(async () => ({ response: { ok: true }, data: {} })),
  getExploreFrameworkDetail: vi.fn(async () => ({
    response: { ok: true },
    data: { id: "99999999-9999-9999-9999-999999999999", title: "Supplier Audit Kit" },
  })),
}));

/** Fill every required framework-request field with valid values. */
async function fillFrameworkRequest() {
  await screen.findByRole("option", { name: "Governance Playbook" });
  fireEvent.change(screen.getByLabelText(/Framework/i), {
    target: { value: "11111111-1111-1111-1111-111111111111" },
  });
  fireEvent.change(screen.getByLabelText(/Review type/i), {
    target: { value: "quality" },
  });
  fireEvent.change(screen.getByLabelText(/What it does/i), {
    target: { value: "Structures governance decisions." },
  });
  fireEvent.change(screen.getByLabelText(/Use case/i), {
    target: { value: "Board oversight." },
  });
  fireEvent.change(screen.getByLabelText(/Jurisdiction/i), {
    target: { value: "global" },
  });
  fireEvent.change(screen.getByLabelText(/Focus areas/i), {
    target: { value: "Controls and audit trail." },
  });
  fireEvent.change(screen.getByLabelText(/Desired outcome/i), {
    target: { value: "Independent quality sign-off." },
  });
}

describe("RequestorPanel framework request", () => {
  it("lists the requester's own frameworks in the picker", async () => {
    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: "Governance Playbook" }),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("option", { name: "Risk Register Template" }),
    ).toBeInTheDocument();
  });

  it("is framework-only: no target-type selector or manual id field", async () => {
    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    expect(screen.queryByLabelText(/Target type/i)).toBeNull();
    expect(screen.queryByLabelText(/Target ID/i)).toBeNull();
  });

  it("keeps the request disabled until review type and brief are filled", async () => {
    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    await screen.findByRole("option", { name: "Governance Playbook" });
    fireEvent.change(screen.getByLabelText(/Framework/i), {
      target: { value: "11111111-1111-1111-1111-111111111111" },
    });

    // Framework picked but review type and brief still empty.
    expect(
      screen.getByRole("button", { name: /Request attestation/i }),
    ).toBeDisabled();
  });

  it("shows a requesting state while the request is in flight", async () => {
    let resolveRequest: (value: unknown) => void = () => {};
    vi.mocked(requestAttestation).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }) as never,
    );

    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    await fillFrameworkRequest();

    fireEvent.click(
      screen.getByRole("button", { name: /Request attestation/i }),
    );

    // Button flips to the busy label and disables while the promise is pending.
    const busy = await screen.findByRole("button", { name: /Requesting/i });
    expect(busy).toBeDisabled();

    resolveRequest({ response: { ok: true }, data: {} });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Request attestation/i }),
      ).toBeInTheDocument(),
    );
  });

  it("submits the review type and structured brief for a framework", async () => {
    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    await fillFrameworkRequest();

    const button = screen.getByRole("button", { name: /Request attestation/i });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => {
      expect(requestAttestation).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            target_type: "framework",
            target_id: "11111111-1111-1111-1111-111111111111",
            review_type: "quality",
            brief: {
              what_it_does: "Structures governance decisions.",
              use_case: "Board oversight.",
              jurisdiction: "global",
              focus_areas: "Controls and audit trail.",
              desired_outcome: "Independent quality sign-off.",
            },
          }),
        }),
      );
    });
  });

  it("opens the fee payment panel when the request returns a client secret", async () => {
    vi.mocked(requestAttestation).mockResolvedValueOnce({
      response: { ok: true },
      data: {
        id: "att-1",
        transaction_id: "txn-1",
        provider: "stripe",
        client_secret: "pi_secret_test",
      },
    } as never);

    render(<RequestorPanel />);
    await screen.findByText("Request Attestation");
    await fillFrameworkRequest();
    fireEvent.click(
      screen.getByRole("button", { name: /Request attestation/i }),
    );

    expect(await screen.findByTestId("funding-panel")).toHaveTextContent(
      "att-1",
    );
  });

  it("redirects to Paystack hosted checkout when the request returns a URL", async () => {
    // A Nigerian requestor pays on Paystack's own page: no in-page fee panel,
    // the browser navigates to the hosted checkout with the fee attached, and
    // the billing country the requestor picked rides along in the request.
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign: vi.fn(), origin: "http://localhost:3000" },
    });
    try {
      vi.mocked(requestAttestation).mockResolvedValueOnce({
        response: { ok: true },
        data: {
          id: "att-3",
          transaction_id: "txn-3",
          provider: "paystack",
          client_secret: null,
          authorization_url: "https://checkout.paystack.com/attestation_001",
        },
      } as never);

      render(<RequestorPanel />);
      await screen.findByText("Request Attestation");
      await fillFrameworkRequest();
      fireEvent.change(screen.getByLabelText(/billing country/i), {
        target: { value: "NG" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: /Request attestation/i }),
      );

      await waitFor(() => {
        expect(window.location.assign).toHaveBeenCalledWith(
          "https://checkout.paystack.com/attestation_001",
        );
      });
      expect(requestAttestation).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({ country: "NG" }),
        }),
      );
      expect(screen.queryByTestId("funding-panel")).toBeNull();
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  it("does not open the fee panel when the request awaits owner consent", async () => {
    vi.mocked(requestAttestation).mockResolvedValueOnce({
      response: { ok: true },
      data: { id: "att-2", status: "pending_owner_consent" },
    } as never);

    render(<RequestorPanel />);
    await screen.findByText("Request Attestation");
    await fillFrameworkRequest();
    fireEvent.click(
      screen.getByRole("button", { name: /Request attestation/i }),
    );

    await waitFor(() => expect(requestAttestation).toHaveBeenCalled());
    expect(screen.queryByTestId("funding-panel")).toBeNull();
  });
});

/** One requestor-visible attestation in the given status. */
function attestationInStatus(status: string) {
  return {
    id: "att-withdraw-1",
    target_type: "framework",
    target_id: "11111111-1111-1111-1111-111111111111",
    status,
    outcome: null,
    fee_amount: "1200.00",
    currency: "NGN",
    summary: null,
    open_clarification: false,
  };
}

describe("RequestorPanel request list", () => {
  it("summarises a request by title, attestor, next step, and fee", async () => {
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          {
            ...attestationInStatus("in_review"),
            target_title: "Governance Playbook",
            attestor_org_name: "Lagos Assurance",
            completion_due_at: "2026-09-20T00:00:00Z",
          },
        ],
      },
    } as never);

    render(<RequestorPanel />);

    expect(
      await screen.findByRole("heading", { name: "Governance Playbook" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Reviewed by Lagos Assurance")).toBeInTheDocument();
    expect(
      screen.getByText("Lagos Assurance is reviewing. Report due 20 Sep 2026."),
    ).toBeInTheDocument();
    expect(screen.getByText(/1,200/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /View details/i }),
    ).toHaveAttribute("href", "/attestations/att-withdraw-1");
  });

  it("falls back to a generic target label when no title is exposed", async () => {
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [attestationInStatus("matching")] },
    } as never);

    render(<RequestorPanel />);

    expect(
      await screen.findByRole("heading", { name: "Framework" }),
    ).toBeInTheDocument();
  });

  it("keeps the decision and withdrawal controls on the detail page", async () => {
    // The list is a summary: accepting, disputing, and withdrawing all need
    // the report and the refund copy beside them, which only detail has.
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          attestationInStatus("report_submitted"),
          { ...attestationInStatus("matching"), id: "att-2" },
        ],
      },
    } as never);

    render(<RequestorPanel />);

    await screen.findByText(/Report ready/i);
    expect(screen.queryByRole("button", { name: /Accept report/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Raise dispute/i })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Withdraw request/i }),
    ).toBeNull();
  });

  it("keeps a payment route open for an unpaid request", async () => {
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [attestationInStatus("pending_fee")] },
    } as never);

    render(<RequestorPanel />);

    await screen.findByText(/Awaiting payment/i);
    expect(screen.getByRole("link", { name: /Pay fee/i })).toHaveAttribute(
      "href",
      "/attestations/att-withdraw-1",
    );
  });

  it("flags a request with an unanswered attestor question", async () => {
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          { ...attestationInStatus("in_review"), open_clarification: true },
        ],
      },
    } as never);

    render(<RequestorPanel />);

    expect(
      await screen.findByText(
        "The attestor asked a question — open details to answer.",
      ),
    ).toBeInTheDocument();
  });
});

describe("RequestorPanel prefilled target", () => {
  it("pins an external framework and warns that the owner must approve", async () => {
    searchParams.value = "99999999-9999-9999-9999-999999999999";
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [] },
    } as never);

    render(<RequestorPanel />);

    expect(
      await screen.findByText("Request an attestation"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Supplier Audit Kit")).toBeInTheDocument();
    expect(
      screen.getByText(
        "The framework owner must approve this request before you pay.",
      ),
    ).toBeInTheDocument();
    // The framework is fixed by the link that opened the form.
    expect(screen.queryByLabelText(/^Framework/i)).toBeNull();
  });

  it("pins one of the requester's own frameworks without the owner note", async () => {
    searchParams.value = "11111111-1111-1111-1111-111111111111";
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [] },
    } as never);

    render(<RequestorPanel />);

    await screen.findByText("Request an attestation");
    expect(
      await screen.findByText("Governance Playbook"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Framework/i)).toBeNull();
    expect(
      screen.queryByText(
        "The framework owner must approve this request before you pay.",
      ),
    ).toBeNull();
    expect(getExploreFrameworkDetail).not.toHaveBeenCalled();
  });

  it("requests the pinned framework when the brief is submitted", async () => {
    searchParams.value = "99999999-9999-9999-9999-999999999999";
    vi.mocked(listAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [] },
    } as never);

    render(<RequestorPanel />);

    await screen.findByText("Supplier Audit Kit");
    fireEvent.change(screen.getByLabelText(/Review type/i), {
      target: { value: "quality" },
    });
    fireEvent.change(screen.getByLabelText(/What it does/i), {
      target: { value: "Structures supplier audits." },
    });
    fireEvent.change(screen.getByLabelText(/Use case/i), {
      target: { value: "Procurement." },
    });
    fireEvent.change(screen.getByLabelText(/Jurisdiction/i), {
      target: { value: "global" },
    });
    fireEvent.change(screen.getByLabelText(/Focus areas/i), {
      target: { value: "Controls." },
    });
    fireEvent.change(screen.getByLabelText(/Desired outcome/i), {
      target: { value: "Sign-off." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Request attestation/i }),
    );

    await waitFor(() => {
      expect(requestAttestation).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            target_type: "framework",
            target_id: "99999999-9999-9999-9999-999999999999",
          }),
        }),
      );
    });
  });
});
