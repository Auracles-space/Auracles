import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewingMemberPicker } from "@/components/modules/organizations/attestor/reviewing-member-picker";
import { listMembersV1OrgsOrgIdMembersGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ 
  listMembersV1OrgsOrgIdMembersGet: vi.fn() 
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("ReviewingMemberPicker", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists members and selects one", async () => {
    vi.mocked(listMembersV1OrgsOrgIdMembersGet).mockResolvedValue(
      ok({ members: [
        { id: "mem-1", user_id: "u1", display_name: "Ada", email: null, role: "member", joined_at: "2026-07-01T00:00:00Z" },
        { id: "mem-2", user_id: "u2", display_name: "Bob", email: null, role: "member", joined_at: "2026-07-01T00:00:00Z" }
      ] })
    );
    const onChange = vi.fn();
    render(<ReviewingMemberPicker orgId="org-1" value="" onChange={onChange} />);
    
    await waitFor(() => screen.getByText(/Ada/));
    fireEvent.click(screen.getByLabelText(/Ada/));
    
    expect(onChange).toHaveBeenCalledWith("mem-1");
  });
});
