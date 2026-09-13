import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listMembersV1OrgsOrgIdMembersGet as listMembers,
  nominateOrgAttestorTrialMember,
} from "@/lib/generated/sdk.gen";
import { TrialMemberGate } from "./trial-member-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMembersV1OrgsOrgIdMembersGet: vi.fn(),
  nominateOrgAttestorTrialMember: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));

const MEMBERS = [
  { id: "member-1", user_id: "user-1", display_name: "Ada Lovelace", email: "ada@x.io", role: "member", joined_at: "2026-01-01T00:00:00Z", nda_signed: true },
  { id: "member-2", user_id: "user-2", display_name: "Alan Turing", email: "alan@x.io", role: "admin", joined_at: "2026-01-02T00:00:00Z", nda_signed: true },
];

describe("TrialMemberGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMembers).mockResolvedValue({ data: { members: MEMBERS } } as never);
    vi.mocked(nominateOrgAttestorTrialMember).mockResolvedValue({ data: {} } as never);
  });

  it("nominates the selected member by id from the dropdown", async () => {
    render(<TrialMemberGate application={null} onChange={vi.fn()} />);

    // The picker lists org members by name, not raw ids.
    await screen.findByRole("option", { name: /Ada Lovelace/ });

    fireEvent.change(screen.getByLabelText(/Nominee/i), {
      target: { value: "member-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Nominate Trial Member/i }));

    await waitFor(() =>
      expect(nominateOrgAttestorTrialMember).toHaveBeenCalled(),
    );
    const arg = vi.mocked(nominateOrgAttestorTrialMember).mock.calls[0][0];
    expect(arg.body.member_id).toBe("member-2");
  });

  it("guides the user to the NDA page when nomination is blocked by nda_required", async () => {
    vi.mocked(nominateOrgAttestorTrialMember).mockResolvedValue({
      error: { detail: { error_code: "nda_required" } },
    } as never);
    render(<TrialMemberGate application={null} onChange={vi.fn()} />);
    await screen.findByRole("option", { name: /Ada Lovelace/ });

    fireEvent.change(screen.getByLabelText(/Nominee/i), {
      target: { value: "member-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Nominate Trial Member/i }));

    await waitFor(() =>
      expect(screen.getByText(/must sign the organization NDA/i)).toBeTruthy(),
    );
    const link = screen.getByRole("link", { name: /sign the NDA/i });
    expect(link.getAttribute("href")).toBe("/dashboard/organizations/org-1/nda");
  });

  it("omits members who have not signed the NDA from the picker", async () => {
    vi.mocked(listMembers).mockResolvedValue({
      data: {
        members: [
          MEMBERS[0],
          { ...MEMBERS[1], nda_signed: false },
        ],
      },
    } as never);
    render(<TrialMemberGate application={null} onChange={vi.fn()} />);

    await screen.findByRole("option", { name: /Ada Lovelace/ });
    expect(screen.queryByRole("option", { name: /Alan Turing/ })).toBeNull();
  });

  it("names the nominated member instead of showing their raw id", async () => {
    render(
      <TrialMemberGate
        application={{ trial_member_id: "member-2" } as never}
        onChange={vi.fn()}
      />,
    );

    expect(await screen.findByText("Alan Turing")).toBeInTheDocument();
    expect(screen.queryByText("member-2")).not.toBeInTheDocument();
    // No picker once a nominee is stamped.
    expect(screen.queryByLabelText(/Nominee/i)).not.toBeInTheDocument();
  });

  it("still names a nominee who has since let their NDA lapse", async () => {
    // The picker filters to NDA-signed members, but the nominee lookup must
    // not: the trial was staffed already and the owner needs to know by whom.
    vi.mocked(listMembers).mockResolvedValue({
      data: { members: [MEMBERS[0], { ...MEMBERS[1], nda_signed: false }] },
    } as never);
    render(
      <TrialMemberGate
        application={{ trial_member_id: "member-2" } as never}
        onChange={vi.fn()}
      />,
    );

    expect(await screen.findByText("Alan Turing")).toBeInTheDocument();
  });

  it("keeps the nominate button disabled until a member is chosen", async () => {
    render(<TrialMemberGate application={null} onChange={vi.fn()} />);
    await screen.findByRole("option", { name: /Ada Lovelace/ });

    expect(
      screen.getByRole("button", { name: /Nominate Trial Member/i }),
    ).toHaveProperty("disabled", true);
  });
});
