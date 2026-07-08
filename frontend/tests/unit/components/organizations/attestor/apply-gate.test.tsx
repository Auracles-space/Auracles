import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApplyGate } from "@/components/modules/organizations/attestor/apply-gate";
import { updateOrgAttestorApplication } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: (e: unknown) => (e as Error).message,
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  createOrgAttestorApplication: vi.fn(),
  updateOrgAttestorApplication: vi.fn(),
  submitOrgAttestorApplication: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("ApplyGate", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves an edited draft field", async () => {
    vi.mocked(updateOrgAttestorApplication).mockResolvedValue(ok({ status: "draft" }) as unknown);
    const onChange = vi.fn();
    render(<ApplyGate orgId="org-1" onChange={onChange}
      application={{ status: "needs_info", legal_name: "Audit Ltd", credentials_summary: "Sum" } as never} />);
    fireEvent.change(screen.getByLabelText(/legal name/i), { target: { value: "Audit Ltd" } });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    await waitFor(() => expect(vi.mocked(updateOrgAttestorApplication)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" }, body: expect.objectContaining({ legal_name: "Audit Ltd" }) }),
    ));
    expect(onChange).toHaveBeenCalled();
  });

  it("shows admin feedback when status is needs_info", () => {
    render(<ApplyGate orgId="org-1" onChange={vi.fn()}
      application={{ status: "needs_info", admin_feedback: "Add incorporation cert" } as never} />);
    expect(screen.getByText(/Add incorporation cert/)).toBeInTheDocument();
  });
});
