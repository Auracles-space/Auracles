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

    fireEvent.change(
      screen.getByPlaceholderText("e.g. Project Management Professional"),
      {
      target: { value: "Healthcare Compliance Lead" },
      },
    );
    fireEvent.change(
      screen.getByPlaceholderText("e.g. Project Management Institute"),
      {
      target: { value: "Auracles Institute" },
      },
    );
    fireEvent.change(screen.getByLabelText(/Issued date/), {
      target: { value: "2026-01-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add credentials" }));

    await waitFor(() => {
      expect(createCredential).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            credential_type: null,
            expires_date: null,
            issued_date: "2026-01-01",
            issuer: "Auracles Institute",
            issuer_type: null,
            reference_number: null,
            title: "Healthcare Compliance Lead",
            verification_url: null,
          },
        }),
      );
    });
    expect(await screen.findByText("Healthcare Compliance Lead")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Edit credential" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Upload evidence")).toBeInTheDocument();
    expect(
      screen.getByText("PDF, Word, and image files up to 10 MB."),
    ).toBeInTheDocument();
  });

  it("starts in create mode with explicit evidence guidance", async () => {
    render(<CredentialManager />);

    expect(
      await screen.findByRole("heading", { name: "Create credential" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("Save the credential once to unlock evidence upload."),
    ).toHaveLength(2);
    expect(screen.getByLabelText("Upload evidence")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Add credentials" }),
    ).toBeInTheDocument();
  });
});
