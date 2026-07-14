import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RequestorPanel } from "./requestor-panel";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptAttestationReport: vi.fn(),
  createAttestationDispute: vi.fn(),
  listAttestations: vi.fn(async () => ({
    response: { ok: true },
    data: { attestations: [] },
  })),
  requestAttestation: vi.fn(),
}));

describe("RequestorPanel specializations visibility", () => {
  it("hides the specializations input for framework targets", async () => {
    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    expect(screen.queryByLabelText(/Specializations/i)).toBeNull();
  });

  it("does not require requester-typed lists for framework targets", async () => {
    render(<RequestorPanel />);

    await screen.findByText("Request Attestation");
    fireEvent.change(screen.getByLabelText(/Target ID/i), {
      target: { value: "11111111-1111-1111-1111-111111111111" },
    });

    expect(
      screen.getByRole("button", { name: /Start fee escrow/i }),
    ).toBeEnabled();
  });
});
