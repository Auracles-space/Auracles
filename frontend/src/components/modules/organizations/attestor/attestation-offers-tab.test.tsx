import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet as listOffers,
} from "@/lib/generated/sdk.gen";
import { AttestationOffersTab } from "./attestation-offers-tab";

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet: vi.fn(),
  declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

vi.mock("./accept-and-staff-dialog", () => ({
  AcceptAndStaffDialog: () => null,
}));

function offer(overrides: Record<string, unknown>) {
  return {
    offer_id: "offer-1",
    attestation_id: "att-1",
    target_type: "framework",
    target_id: "fw-1",
    target_title: null,
    status: "offered",
    cohort_index: 0,
    match_score: 88,
    offered_at: "2026-07-16T00:00:00Z",
    expires_at: "2099-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("AttestationOffersTab preview", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the framework title when present", async () => {
    vi.mocked(listOffers).mockResolvedValue({
      response: { ok: true },
      data: {
        offers: [offer({ target_title: "Revenue Ops Playbook" })],
      },
    } as never);

    render(<AttestationOffersTab />);

    expect(
      await screen.findByText("Revenue Ops Playbook"),
    ).toBeInTheDocument();
  });

  it("hides accept/decline once the offer is accepted", async () => {
    vi.mocked(listOffers).mockResolvedValue({
      response: { ok: true },
      data: {
        offers: [offer({ status: "accepted", target_title: "Ops Playbook" })],
      },
    } as never);

    render(<AttestationOffersTab />);

    await screen.findByText("Ops Playbook");
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /decline/i })).not.toBeInTheDocument();
    expect(screen.getByText(/member assigned/i)).toBeInTheDocument();
  });

  it("shows accept/decline while the offer is open", async () => {
    vi.mocked(listOffers).mockResolvedValue({
      response: { ok: true },
      data: { offers: [offer({ status: "offered", target_title: "Ops Playbook" })] },
    } as never);

    render(<AttestationOffersTab />);

    expect(await screen.findByRole("button", { name: /accept/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /decline/i })).toBeInTheDocument();
  });

  it("falls back to the target type when there is no title", async () => {
    vi.mocked(listOffers).mockResolvedValue({
      response: { ok: true },
      data: {
        offers: [
          offer({ offer_id: "o2", target_type: "contributor", target_title: null }),
        ],
      },
    } as never);

    render(<AttestationOffersTab />);

    // "contributor" appears as the fallback heading (and the type badge).
    expect(
      (await screen.findAllByText("contributor")).length,
    ).toBeGreaterThan(0);
  });
});
