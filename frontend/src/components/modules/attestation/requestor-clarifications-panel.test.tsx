import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listAttestationClarifications,
  respondAttestationClarification,
} from "@/lib/generated/sdk.gen";
import { RequestorClarificationsPanel } from "./requestor-clarifications-panel";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "error",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestationClarifications: vi.fn(),
  respondAttestationClarification: vi.fn(),
}));

function clarification(overrides: Record<string, unknown>) {
  return {
    id: "c1",
    attestation_id: "att-1",
    question: "What jurisdiction applies?",
    response: null,
    sent_at: "2026-07-16T00:00:00Z",
    response_due_at: "2026-07-18T00:00:00Z",
    responded_at: null,
    status: "open",
    ...overrides,
  };
}

describe("RequestorClarificationsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders nothing when there are no clarifications", async () => {
    vi.mocked(listAttestationClarifications).mockResolvedValue({
      response: { ok: true },
      data: [],
    } as never);

    const { container } = render(
      <RequestorClarificationsPanel attestationId="att-1" />,
    );
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("lets the requestor answer an open question", async () => {
    vi.mocked(listAttestationClarifications).mockResolvedValue({
      response: { ok: true },
      data: [clarification({})],
    } as never);
    vi.mocked(respondAttestationClarification).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);

    render(<RequestorClarificationsPanel attestationId="att-1" />);

    await screen.findByText("What jurisdiction applies?");
    fireEvent.change(screen.getByPlaceholderText(/type your answer/i), {
      target: { value: "United States" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send answer/i }));

    await waitFor(() => {
      expect(respondAttestationClarification).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { response: "United States" },
          path: { attestation_id: "att-1", clarification_id: "c1" },
        }),
      );
    });
  });

  it("shows an answered question read-only", async () => {
    vi.mocked(listAttestationClarifications).mockResolvedValue({
      response: { ok: true },
      data: [
        clarification({ status: "answered", response: "United States" }),
      ],
    } as never);

    render(<RequestorClarificationsPanel attestationId="att-1" />);

    await screen.findByText("What jurisdiction applies?");
    expect(screen.getByText("United States")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /send answer/i }),
    ).not.toBeInTheDocument();
  });
});
