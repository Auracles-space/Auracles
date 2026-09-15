import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet as listOffers,
  declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost as declineOffer,
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
    match_score: 0.873,
    offered_at: "2026-09-14T00:00:00Z",
    expires_at: "2026-09-15T17:00:00Z",
    ...overrides,
  };
}

function mockOffers(...offers: Record<string, unknown>[]) {
  vi.mocked(listOffers).mockResolvedValue({
    response: { ok: true },
    data: { offers },
  } as never);
}

describe("AttestationOffersTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-14T12:00:00Z"));
  });

  afterEach(() => vi.useRealTimers());

  it("shows the framework title when present", async () => {
    mockOffers(offer({ target_title: "Revenue Ops Playbook" }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("Revenue Ops Playbook")).toBeInTheDocument();
  });

  it("falls back to the target type when there is no title", async () => {
    mockOffers(offer({ target_type: "contributor", target_title: null }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("Contributor")).toBeInTheDocument();
  });

  it("renders the match score as a whole percentage", async () => {
    mockOffers(offer({ match_score: 0.873 }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("87% match")).toBeInTheDocument();
  });

  it("renders a zero match score rather than treating it as missing", async () => {
    mockOffers(offer({ match_score: 0 }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("0% match")).toBeInTheDocument();
  });

  it("says there is no score when the matcher did not produce one", async () => {
    mockOffers(offer({ match_score: null }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("No score")).toBeInTheDocument();
  });

  it("counts down to the offer expiry and drops the raw attestation id", async () => {
    mockOffers(offer({ expires_at: "2026-09-15T17:00:00Z" }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("Expires in 29 h")).toBeInTheDocument();
    expect(screen.queryByText(/att-1/)).not.toBeInTheDocument();
  });

  it("marks a lapsed offer as expired and hides its actions", async () => {
    mockOffers(offer({ expires_at: "2026-09-13T00:00:00Z" }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("Expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });

  it("reads an open offer as awaiting the org's response", async () => {
    mockOffers(offer({ status: "offered" }));

    render(<AttestationOffersTab />);

    expect(await screen.findByText("Awaiting your response")).toBeInTheDocument();
  });

  it("separates open offers, reviews in progress, and attested work", async () => {
    // Accepted offers stayed in one list forever, so finished attestations
    // sat among the offers still waiting for an answer.
    mockOffers(
      offer({ offer_id: "o-open", target_title: "Open Playbook", status: "offered" }),
      offer({
        offer_id: "o-review",
        attestation_id: "att-review",
        target_title: "Review Playbook",
        status: "accepted",
        attestation_status: "in_review",
      }),
      offer({
        offer_id: "o-done",
        attestation_id: "att-done",
        target_title: "Attested Playbook",
        status: "accepted",
        attestation_status: "released",
      }),
    );

    render(<AttestationOffersTab />);

    const open = await screen.findByRole("region", { name: "Open offers" });
    const inReview = screen.getByRole("region", { name: "In review" });
    const attested = screen.getByRole("region", { name: "Attested" });
    expect(within(open).getByText("Open Playbook")).toBeInTheDocument();
    expect(within(inReview).getByText("Review Playbook")).toBeInTheDocument();
    expect(within(attested).getByText("Attested Playbook")).toBeInTheDocument();
    expect(within(attested).queryByText("Review Playbook")).toBeNull();
  });

  it("links to the workspace once the offer is accepted", async () => {
    mockOffers(offer({ status: "accepted", attestation_id: "att-9" }));

    render(<AttestationOffersTab />);

    const link = await screen.findByRole("link", { name: "Open workspace" });
    expect(link).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/attestations/att-9",
    );
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("declines through a confirm dialog and omits an empty reason", async () => {
    mockOffers(offer({}));
    vi.mocked(declineOffer).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);

    render(<AttestationOffersTab />);

    fireEvent.click(await screen.findByRole("button", { name: "Decline" }));
    expect(await screen.findByText("Decline this offer?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Decline offer" }));

    await waitFor(() => expect(declineOffer).toHaveBeenCalled());
    expect(vi.mocked(declineOffer).mock.calls[0][0]).toMatchObject({
      path: { org_id: "org-1", offer_id: "offer-1" },
      body: {},
    });
  });

  it("sends the typed reason with the decline", async () => {
    mockOffers(offer({}));
    vi.mocked(declineOffer).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);

    render(<AttestationOffersTab />);

    fireEvent.click(await screen.findByRole("button", { name: "Decline" }));
    fireEvent.change(screen.getByLabelText("Reason (optional)"), {
      target: { value: "Outside our jurisdiction" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Decline offer" }));

    await waitFor(() => expect(declineOffer).toHaveBeenCalled());
    expect(vi.mocked(declineOffer).mock.calls[0][0]).toMatchObject({
      body: { reason: "Outside our jurisdiction" },
    });
  });
});
