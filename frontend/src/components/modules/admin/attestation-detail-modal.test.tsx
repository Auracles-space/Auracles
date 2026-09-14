import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { getAdminAttestationDetail } from "@/lib/generated/sdk.gen";
import { AttestationDetailModal } from "./attestation-detail-modal";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAdminAttestationDetail: vi.fn(),
}));

describe("AttestationDetailModal", () => {
  it("shows the status and the offer's org", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-1",
          target_type: "framework",
          target_id: "fw-1",
          requestor_id: "user-1",
          attestor_org_id: null,
          status: "offered",
          outcome: null,
          review_type: "quality",
          requested_specializations: [],
          requested_jurisdictions: [],
          fee_amount: "500.00",
          currency: "USD",
          escrow_id: "esc-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
        offers: [
          {
            org_id: "org-1",
            org_name: "Acme Advisory",
            status: "offered",
            cohort_index: 0,
            offered_at: "2026-07-16T01:00:00Z",
            expires_at: "2026-07-18T01:00:00Z",
            responded_at: null,
          },
        ],
      },
    } as never);

    render(
      <AttestationDetailModal attestationId="att-1" onClose={vi.fn()} />,
    );

    expect(await screen.findByText("Acme Advisory")).toBeInTheDocument();
    expect(screen.getByText("Offers (1)")).toBeInTheDocument();
    expect(getAdminAttestationDetail).toHaveBeenCalledWith(
      expect.objectContaining({ path: { attestation_id: "att-1" } }),
    );
  });

  it("names the admin step in the admin's own vocabulary", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-2",
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
          currency: "NGN",
          escrow_id: "esc-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
        offers: [],
      },
    } as never);

    render(<AttestationDetailModal attestationId="att-2" onClose={vi.fn()} />);

    expect(await screen.findByText("Needs admin")).toBeInTheDocument();
    expect(screen.queryByText("Finding attestor")).toBeNull();
  });

  it("shows why an org declined its offer", async () => {
    vi.mocked(getAdminAttestationDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        attestation: {
          id: "att-3",
          target_type: "framework",
          target_id: "fw-1",
          requestor_id: "user-1",
          attestor_org_id: null,
          status: "matching",
          outcome: null,
          review_type: "quality",
          requested_specializations: [],
          requested_jurisdictions: [],
          fee_amount: "500.00",
          currency: "NGN",
          escrow_id: "esc-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
        offers: [
          {
            org_id: "org-1",
            org_name: "Acme Advisory",
            status: "declined",
            cohort_index: 0,
            offered_at: "2026-07-16T01:00:00Z",
            expires_at: "2026-07-18T01:00:00Z",
            responded_at: "2026-07-17T01:00:00Z",
            decline_reason: "Outside our jurisdiction",
          },
        ],
      },
    } as never);

    render(<AttestationDetailModal attestationId="att-3" onClose={vi.fn()} />);

    expect(
      await screen.findByText("Reason: Outside our jurisdiction"),
    ).toBeInTheDocument();
    expect(screen.getByText("Declined")).toBeInTheDocument();
  });
});
