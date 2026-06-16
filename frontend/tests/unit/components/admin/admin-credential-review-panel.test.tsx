import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminCredentialReviewPanel } from "@/components/modules/admin/admin-credential-review-panel";
import {
  downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet,
  listCredentialReviewQueueV1AdminCredentialsGet,
  rejectCredentialV1AdminCredentialsCredentialIdRejectPost,
  verifyCredentialV1AdminCredentialsCredentialIdVerifyPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet: vi.fn(),
  listCredentialReviewQueueV1AdminCredentialsGet: vi.fn(),
  rejectCredentialV1AdminCredentialsCredentialIdRejectPost: vi.fn(),
  verifyCredentialV1AdminCredentialsCredentialIdVerifyPost: vi.fn(),
}));

const credential = {
  created_at: "2026-06-10T00:00:00Z",
  credential_type: "certification",
  evidence_file_keys: ["credentials/abc/diploma.pdf"],
  expires_date: null,
  id: "00000000-0000-4000-8000-000000000041",
  issued_date: "2025-01-01",
  issuer: "Global Institute",
  issuer_type: "institution",
  reference_number: "REF-123",
  rejection_reason: null,
  reviewed_by: null,
  submitted_at: "2026-06-11T00:00:00Z",
  title: "Certified Operating Model Lead",
  updated_at: "2026-06-10T00:00:00Z",
  user_id: "00000000-0000-4000-8000-000000000001",
  verification_status: "pending",
  verification_url: "https://verify.example.com/abc",
  verified_at: null,
};

/**
 * Build a generated-client style success envelope.
 *
 * @param data - Response payload.
 * @param status - HTTP status code.
 */
function ok<T>(data: T, status = 200) {
  return {
    data,
    error: undefined,
    request: new Request("http://testserver"),
    response: new Response(null, { status }),
  };
}

describe("AdminCredentialReviewPanel", () => {
  beforeEach(() => {
    vi.mocked(listCredentialReviewQueueV1AdminCredentialsGet).mockReset();
    vi.mocked(verifyCredentialV1AdminCredentialsCredentialIdVerifyPost).mockReset();
    vi.mocked(rejectCredentialV1AdminCredentialsCredentialIdRejectPost).mockReset();
    vi.mocked(
      downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet,
    ).mockReset();
    vi.mocked(listCredentialReviewQueueV1AdminCredentialsGet).mockResolvedValue(
      ok({ credentials: [credential] }),
    );
  });

  it("renders pending credentials from the queue", async () => {
    render(<AdminCredentialReviewPanel />);

    expect(
      await screen.findByText("Certified Operating Model Lead"),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(listCredentialReviewQueueV1AdminCredentialsGet).toHaveBeenCalledWith(
        expect.objectContaining({ query: { status: "pending" } }),
      );
    });
  });

  it("verifies a credential with the correct id", async () => {
    vi.mocked(
      verifyCredentialV1AdminCredentialsCredentialIdVerifyPost,
    ).mockResolvedValue(ok({ ...credential, verification_status: "verified" }));

    render(<AdminCredentialReviewPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Verify" }));

    await waitFor(() => {
      expect(
        verifyCredentialV1AdminCredentialsCredentialIdVerifyPost,
      ).toHaveBeenCalledWith(
        expect.objectContaining({ path: { credential_id: credential.id } }),
      );
    });
  });

  it("requires a reason before rejecting, then sends it", async () => {
    vi.mocked(
      rejectCredentialV1AdminCredentialsCredentialIdRejectPost,
    ).mockResolvedValue(
      ok({
        ...credential,
        rejection_reason: "Insufficient evidence",
        verification_status: "rejected",
      }),
    );

    render(<AdminCredentialReviewPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

    // Confirming with an empty reason must not call the reject endpoint.
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirm reject" }),
    );
    expect(
      rejectCredentialV1AdminCredentialsCredentialIdRejectPost,
    ).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Rejection reason"), {
      target: { value: "Insufficient evidence" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm reject" }));

    await waitFor(() => {
      expect(
        rejectCredentialV1AdminCredentialsCredentialIdRejectPost,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { reason: "Insufficient evidence" },
          path: { credential_id: credential.id },
        }),
      );
    });
  });

  it("opens evidence via the admin download endpoint", async () => {
    vi.mocked(
      downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet,
    ).mockResolvedValue(ok({ url: "https://s3.example.com/signed" }));
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<AdminCredentialReviewPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "View" }));

    await waitFor(() => {
      expect(
        downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { credential_id: credential.id },
          query: { key: "credentials/abc/diploma.pdf" },
        }),
      );
    });
    expect(openSpy).toHaveBeenCalledWith(
      "https://s3.example.com/signed",
      "_blank",
      "noopener,noreferrer",
    );
    openSpy.mockRestore();
  });
});
