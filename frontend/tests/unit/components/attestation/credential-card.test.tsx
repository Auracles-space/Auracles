import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CredentialCard } from "@/components/modules/attestation/credential-card";
import { downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet } from "@/lib/generated/sdk.gen";
import type { CredentialResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet: vi.fn(),
}));

const baseCredential: CredentialResponse = {
  created_at: "2026-06-10T00:00:00Z",
  credential_type: null,
  evidence_file_keys: [],
  expired: false,
  expires_date: null,
  id: "00000000-0000-4000-8000-000000000041",
  issued_date: "2025-01-01",
  issuer: "Global Institute",
  issuer_type: null,
  reference_number: null,
  rejection_reason: null,
  reviewed_by: null,
  submitted_at: null,
  title: "Certified Operating Model Lead",
  updated_at: "2026-06-10T00:00:00Z",
  user_id: "00000000-0000-4000-8000-000000000001",
  verification_status: "unverified",
  verification_url: null,
  verified_at: null,
};

function renderCard(overrides: Partial<CredentialResponse> = {}) {
  return render(
    <CredentialCard
      busy={false}
      credential={{ ...baseCredential, ...overrides }}
      onDelete={vi.fn()}
      onEdit={vi.fn()}
      onSubmitForVerification={vi.fn()}
    />,
  );
}

describe("CredentialCard", () => {
  beforeEach(() => {
    vi.mocked(
      downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet,
    ).mockReset();
  });

  it("disables Submit for verification with no evidence, url, or reference", () => {
    renderCard();
    const submit = screen.getByRole("button", { name: "Submit for verification" });
    expect(submit).toBeDisabled();
  });

  it("enables Submit for verification when a reference number is present", () => {
    renderCard({ reference_number: "REF-123" });
    const submit = screen.getByRole("button", { name: "Submit for verification" });
    expect(submit).toBeEnabled();
  });

  it("renders the rejection reason when status is rejected", () => {
    renderCard({
      rejection_reason: "Issuer could not be verified.",
      verification_status: "rejected",
    });
    expect(screen.getByText("Issuer could not be verified.")).toBeInTheDocument();
  });

  it("does not render the edit-reset warning in the card", () => {
    renderCard({ verification_status: "verified" });
    expect(
      screen.queryByText(/will reset verification and require re-review/i),
    ).not.toBeInTheDocument();
  });

  it("hides Submit for verification when the credential is already pending", () => {
    renderCard({ reference_number: "REF-123", verification_status: "pending" });
    expect(
      screen.queryByRole("button", { name: "Submit for verification" }),
    ).not.toBeInTheDocument();
  });

  it("clicking View downloads the evidence file and opens the returned url", async () => {
    const openSpy = vi
      .spyOn(window, "open")
      .mockImplementation(() => null);
    vi.mocked(
      downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet,
    ).mockResolvedValue({
      data: { url: "https://s3.example/presigned-download" },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    renderCard({
      evidence_file_keys: ["credentials/cred-1/evidence/diploma.pdf"],
    });

    expect(screen.getByText("diploma.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View" }));

    await waitFor(() => {
      expect(
        downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { credential_id: "00000000-0000-4000-8000-000000000041" },
          query: { key: "credentials/cred-1/evidence/diploma.pdf" },
        }),
      );
    });

    await waitFor(() => {
      expect(openSpy).toHaveBeenCalledWith(
        "https://s3.example/presigned-download",
        "_blank",
        "noopener,noreferrer",
      );
    });

    openSpy.mockRestore();
  });
});
