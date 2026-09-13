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
      application={{ status: "needs_info", credentials_summary: "Sum" } as never} />);
    // Legal identity is no longer edited here — it belongs to the org's
    // verification page — so the draft is exercised through its own content.
    fireEvent.change(screen.getByLabelText(/credentials summary/i), {
      target: { value: "Two decades of compliance work." },
    });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    await waitFor(() => expect(vi.mocked(updateOrgAttestorApplication)).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1" },
        body: expect.objectContaining({
          credentials_summary: "Two decades of compliance work.",
        }),
      }),
    ));
    expect(onChange).toHaveBeenCalled();
  });

  it("leaves admin feedback to the gate card so it is not shown twice", () => {
    render(<ApplyGate orgId="org-1" onChange={vi.fn()}
      application={{ status: "needs_info", admin_feedback: "Add incorporation cert" } as never} />);
    expect(screen.queryByText(/Add incorporation cert/)).not.toBeInTheDocument();
  });
});
