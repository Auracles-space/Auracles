import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AcceptAndStaffDialog } from "@/components/modules/organizations/attestor/accept-and-staff-dialog";
import { acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost, listMembersV1OrgsOrgIdMembersGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn((r) => (r?.response?.status === 409 ? "Member at capacity" : "err")),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ 
  acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost: vi.fn(), 
  listMembersV1OrgsOrgIdMembersGet: vi.fn() 
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AcceptAndStaffDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("accepts with the chosen reviewing_member_id", async () => {
    vi.mocked(listMembersV1OrgsOrgIdMembersGet).mockResolvedValue(
      ok({ members: [{ id: "mem-1", user_id: "u1", display_name: "Ada", email: "ada@ex.com", role: "member", joined_at: "2026-07-01T00:00:00Z" }] })
    );
    vi.mocked(acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost).mockResolvedValue(
      ok({ status: "accepted" }) as any
    );
    const onDone = vi.fn();
    const onClose = vi.fn();
    render(<AcceptAndStaffDialog orgId="org-1" offerId="offer-1" onDone={onDone} onClose={onClose} />);
    await waitFor(() => screen.getByText(/Ada/));
    fireEvent.click(screen.getByLabelText(/Ada/));
    fireEvent.click(screen.getByRole("button", { name: /accept/i }));
    await waitFor(() => expect(vi.mocked(acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost)).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", offer_id: "offer-1" },
        body: { reviewing_member_id: "mem-1" },
      }),
    ));
    expect(onDone).toHaveBeenCalled();
  });
});
