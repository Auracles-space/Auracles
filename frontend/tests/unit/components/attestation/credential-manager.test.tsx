import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CredentialManager } from "@/components/modules/attestation/credential-manager";
import { createCredential, listCredentials } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createCredential: vi.fn(),
  listCredentials: vi.fn(),
}));

const credential = {
  created_at: "2026-06-10T00:00:00Z",
  evidence_file_keys: [],
  expires_date: null,
  id: "00000000-0000-4000-8000-000000000041",
  issued_date: "2025-01-01",
  issuer: "Global Institute",
  title: "Certified Operating Model Lead",
  updated_at: "2026-06-10T00:00:00Z",
  user_id: "00000000-0000-4000-8000-000000000001",
};

describe("CredentialManager", () => {
  beforeEach(() => {
    vi.mocked(createCredential).mockReset();
    vi.mocked(listCredentials).mockReset();
    vi.mocked(listCredentials).mockResolvedValue({
      data: { credentials: [credential] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
  });

  it("lists credentials and creates a new credential", async () => {
    vi.mocked(createCredential).mockResolvedValue({
      data: {
        ...credential,
        id: "00000000-0000-4000-8000-000000000042",
        title: "Healthcare Compliance Lead",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 201 }),
    });

    render(<CredentialManager />);

    expect(
      await screen.findByText("Certified Operating Model Lead"),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Credential title"), {
      target: { value: "Healthcare Compliance Lead" },
    });
    fireEvent.change(screen.getByLabelText("Issuer"), {
      target: { value: "Auracles Institute" },
    });
    fireEvent.change(screen.getByLabelText("Issued date"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add credential" }));

    await waitFor(() => {
      expect(createCredential).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            expires_date: null,
            issued_date: "2026-01-01",
            issuer: "Auracles Institute",
            title: "Healthcare Compliance Lead",
          },
        }),
      );
    });
    expect(await screen.findByText("Healthcare Compliance Lead")).toBeInTheDocument();
  });
});
