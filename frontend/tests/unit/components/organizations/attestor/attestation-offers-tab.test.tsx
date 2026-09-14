import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestationOffersTab } from "../../../../../src/components/modules/organizations/attestor/attestation-offers-tab";
import { listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet } from "../../../../../src/lib/generated/sdk.gen";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../../../../../src/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
  configureBrowserClient: vi.fn(),
}));
vi.mock("../../../../../src/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));
vi.mock("../../../../../src/lib/generated/sdk.gen", () => ({
  listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet: vi.fn(),
  declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AttestationOffersTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists an offer by target and match score, never by raw id", async () => {
    vi.mocked(listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet).mockResolvedValueOnce(
      ok({ offers: [{ offer_id: "offer-1", attestation_id: "att-1", target_type: "framework", target_id: "fw-1", target_title: "Growth Playbook", status: "offered", cohort_index: 0, match_score: 0.95, offered_at: "2026-07-01T00:00:00Z", expires_at: "2026-07-20T00:00:00Z" }] })
    );
    render(<AttestationOffersTab />);
    await waitFor(() =>
      expect(screen.getByText("Growth Playbook")).toBeInTheDocument(),
    );
    expect(screen.getByText("95% match")).toBeInTheDocument();
    expect(screen.queryByText(/att-1/)).toBeNull();
  });
});
