import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CredentialForm } from "@/components/modules/attestation/credential-form";
import type { CredentialResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createCredentialEvidenceUploadSessionV1CredentialsCredentialIdUploadsPost:
    vi.fn(),
}));

const existing: CredentialResponse = {
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

describe("CredentialForm evidence uploader", () => {
  it("hides the uploader and shows the save-first hint in create mode", () => {
    render(
      <CredentialForm
        mode="create"
        onSubmit={vi.fn()}
        submitting={false}
      />,
    );

    expect(
      screen.queryByLabelText("Upload evidence"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Save the credential first, then add evidence files."),
    ).toBeInTheDocument();
  });

  it("renders the file input in edit mode", () => {
    render(
      <CredentialForm
        initial={existing}
        mode="edit"
        onSubmit={vi.fn()}
        submitting={false}
      />,
    );

    const input = screen.getByLabelText("Upload evidence");
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("type", "file");
  });
});
