import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { TrialMemberGate } from "@/components/modules/organizations/attestor/trial-member-gate";
import { nominateOrgAttestorTrialMember } from "@/lib/generated/sdk.gen";
import { useOrganization } from "@/components/modules/organizations/organization-context";

vi.mock("@/lib/generated/sdk.gen", () => ({
  nominateOrgAttestorTrialMember: vi.fn(),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: vi.fn(),
}));
vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: (e: unknown) => (e as Error).message,
  getAccessTokenHeaders: () => ({ Authorization: "Bearer token" }),
}));

function ok(data: unknown) {
  return { data, error: undefined };
}

describe("TrialMemberGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nominated message if already nominated", () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as unknown as ReturnType<typeof useOrganization>);
    render(
      <TrialMemberGate
        application={{ trial_member_id: "member-123" } as never}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByText(/Trial member nominated:/i)).toBeInTheDocument();
    expect(screen.getByText("member-123")).toBeInTheDocument();
  });

  it("submits trial member nomination", async () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as unknown as ReturnType<typeof useOrganization>);
    vi.mocked(nominateOrgAttestorTrialMember).mockResolvedValue(ok({}) as never);
    const onChange = vi.fn();
    
    render(<TrialMemberGate application={null} onChange={onChange} />);
    
    fireEvent.change(screen.getByLabelText(/Nominee Member ID/i), { target: { value: "member-123" } });
    fireEvent.click(screen.getByRole("button", { name: /Nominate Trial Member/i }));
    
    await waitFor(() =>
      expect(vi.mocked(nominateOrgAttestorTrialMember)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: {
            member_id: "member-123",
          },
        })
      )
    );
    expect(onChange).toHaveBeenCalled();
  });
});
