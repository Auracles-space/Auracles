import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgNdaPanel } from "@/components/modules/organizations/org-nda-panel";
import { getOrgNda, signOrgNda } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "member" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ getOrgNda: vi.fn(), signOrgNda: vi.fn() }));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgNdaPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("signs the current NDA version", async () => {
    vi.mocked(getOrgNda).mockResolvedValue(ok({ required: true, current_version: "v2", signed_version: null, signed_at: null }));
    vi.mocked(signOrgNda).mockResolvedValue(ok({ required: true, current_version: "v2", signed_version: "v2", signed_at: new Date().toISOString() }));
    render(<OrgNdaPanel />);
    
    // Check that we see something about signing
    await waitFor(() => screen.getByText(/You must sign the latest NDA/i));
    
    fireEvent.click(screen.getByRole("button", { name: /sign/i }));
    
    await waitFor(() => expect(vi.mocked(signOrgNda)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" } })
    ));
    
    // Verify it updates state (might render signed message instead)
    await waitFor(() => screen.getByText(/NDA Signed/i));
  });

  it("styles the panel with design tokens rather than raw palette classes", async () => {
    vi.mocked(getOrgNda).mockResolvedValue(ok({ required: true, current_version: "v2", signed_version: "v2", signed_at: "2026-09-01T00:00:00Z", document: "Terms" }));
    const { container } = render(<OrgNdaPanel />);

    await screen.findByText(/NDA Signed/i);
    const html = container.innerHTML;
    expect(html).not.toMatch(/bg-white|text-neutral-|bg-green-|bg-amber-|border-neutral-|bg-neutral-/);
    const signed = screen.getByText(/NDA Signed/i).closest("div");
    expect(signed?.className).toMatch(/bg-success\/10/);
    expect(signed?.className).toMatch(/text-success/);
    const card = container.querySelector("section");
    expect(card?.className).toMatch(/rounded-2xl/);
    expect(card?.className).toMatch(/bg-surface-1/);
  });

  it("keeps the sign button at a 44px touch target", async () => {
    vi.mocked(getOrgNda).mockResolvedValue(ok({ required: true, current_version: "v2", signed_version: null, signed_at: null, document: "Terms" }));
    render(<OrgNdaPanel />);

    const button = await screen.findByRole("button", { name: /sign nda/i });
    expect(button.className).toMatch(/min-h-1[12]/);
  });
});
