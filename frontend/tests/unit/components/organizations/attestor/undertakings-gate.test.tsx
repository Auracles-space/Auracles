import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { UndertakingsGate } from "@/components/modules/organizations/attestor/undertakings-gate";
import { signOrgAttestorUndertakings } from "@/lib/generated/sdk.gen";
import { useOrganization } from "@/components/modules/organizations/organization-context";

vi.mock("@/lib/generated/sdk.gen", () => ({
  signOrgAttestorUndertakings: vi.fn(),
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

describe("UndertakingsGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders block if not owner", () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "admin", orgId: "org-1" } as never);
    render(<UndertakingsGate application={null} onChange={vi.fn()} />);
    expect(screen.getByText(/Only the organization owner/i)).toBeInTheDocument();
  });

  it("renders signed message if already signed", () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as never);
    render(
      <UndertakingsGate
        application={{ confidentiality_signed_at: "2026-07-07T00:00:00Z" } as never}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByText(/Undertakings have been signed/i)).toBeInTheDocument();
  });

  it("submits undertakings with totp", async () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as never);
    vi.mocked(signOrgAttestorUndertakings).mockResolvedValue(ok({ status: "draft" }) as never);
    const onChange = vi.fn();
    
    render(<UndertakingsGate application={null} onChange={onChange} />);
    
    fireEvent.click(screen.getByLabelText(/accept.*policy/i));
    fireEvent.click(screen.getByLabelText(/accept.*confidentiality/i));
    fireEvent.change(screen.getByLabelText(/authenticator code/i), { target: { value: "123456" } });
    
    fireEvent.click(screen.getByRole("button", { name: /sign undertakings/i }));
    
    await waitFor(() =>
      expect(vi.mocked(signOrgAttestorUndertakings)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: {
            declarations: [],
            accept_policy: true,
            accept_confidentiality: true,
            totp_code: "123456",
          },
        })
      )
    );
    expect(onChange).toHaveBeenCalled();
  });
});
