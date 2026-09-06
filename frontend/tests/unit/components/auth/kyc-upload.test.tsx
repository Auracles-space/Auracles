/**
 * Tests for the manual identity-verification panel.
 *
 * Covers the submit path (validate, presign, upload, confirm), the states the
 * user can be left in, and the client-side guards that stop a bad file before
 * it costs a round trip.
 *
 * Maps to: FR-AUTH-009, FR-SET-004.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KycUpload } from "@/components/modules/auth/kyc-upload";
import {
  confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost,
  getKycStatusV1SettingsKycGet,
  requestKycDocumentUploadUrlV1SettingsKycDocumentsPost,
} from "@/lib/generated/sdk.gen";
import type {
  GetKycStatusV1SettingsKycGetResponse,
  KycDocumentResponse,
} from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ accessToken: "access-token" }),
  },
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  ensureBrowserAccessToken: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost: vi.fn(),
  getKycStatusV1SettingsKycGet: vi.fn(),
  requestKycDocumentUploadUrlV1SettingsKycDocumentsPost: vi.fn(),
}));

describe("KycUpload", () => {
  function ok(data: GetKycStatusV1SettingsKycGetResponse) {
    return {
      data,
      error: undefined,
      response: new Response(null, { status: 200 }),
    };
  }

  function submittedDocument(
    overrides: Partial<KycDocumentResponse> = {},
  ): KycDocumentResponse {
    return {
      created_at: "2026-09-06T09:00:00Z",
      doc_type: "national_id",
      file_size: 240_000,
      id: "doc-1",
      mime_type: "application/pdf",
      notes: null,
      reviewed_at: null,
      scan_status: "clean",
      status: "pending",
      ...overrides,
    };
  }

  function idFile(name = "nin-slip.pdf", type = "application/pdf"): File {
    return new File(["identity-document"], name, { type });
  }

  /** Select a file on the panel's file input and wait for it to be accepted. */
  function chooseFile(file: File): void {
    const input = screen.getByLabelText(/document file/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
  }

  beforeEach(() => {
    vi.mocked(getKycStatusV1SettingsKycGet).mockReset();
    vi.mocked(
      requestKycDocumentUploadUrlV1SettingsKycDocumentsPost,
    ).mockReset();
    vi.mocked(
      confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost,
    ).mockReset();
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "unverified", documents: [] }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    window.history.replaceState({}, "", "/settings/kyc");
  });

  it("uploads the document to storage and confirms it", async () => {
    // The full submit path: presign, POST the multipart form straight to S3,
    // then confirm so the account enters the review queue.
    vi.mocked(
      requestKycDocumentUploadUrlV1SettingsKycDocumentsPost,
    ).mockResolvedValue({
      data: {
        document_id: "doc-77",
        expires_in: 900,
        fields: { "Content-Type": "application/pdf", key: "kyc/u/doc-77.pdf" },
        max_size: 10_485_760,
        upload_url: "https://uploads.example.test",
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(
      confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost,
    ).mockResolvedValue({
      data: submittedDocument({ scan_status: "pending_scan" }),
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<KycUpload />);
    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    chooseFile(idFile());
    fireEvent.click(screen.getByRole("button", { name: /submit for review/i }));

    await waitFor(() => {
      expect(
        confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost,
      ).toHaveBeenCalled();
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "https://uploads.example.test",
      expect.objectContaining({ method: "POST" }),
    );
    expect(
      vi.mocked(confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost)
        .mock.calls[0][0]?.path,
    ).toMatchObject({ document_id: "doc-77" });
  });

  it("rejects an unsupported file type without calling the API", async () => {
    // Catching this in the browser saves a round trip the backend would refuse
    // anyway, and tells the user immediately what is wrong.
    render(<KycUpload />);
    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    chooseFile(idFile("id.zip", "application/zip"));

    // Scoped to the alert region: the same words appear in the field's help
    // text, and only the live region proves the user was actually told.
    expect(screen.getByRole("alert")).toHaveTextContent(/jpg, png, or pdf/i);
    expect(
      requestKycDocumentUploadUrlV1SettingsKycDocumentsPost,
    ).not.toHaveBeenCalled();
  });

  it("keeps submission disabled until a file is chosen", async () => {
    render(<KycUpload />);
    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(
      screen.getByRole("button", { name: /submit for review/i }),
    ).toBeDisabled();
  });

  it("refetches the KYC status when the window regains focus", async () => {
    // Pending on mount, verified by the time the user tabs back — an admin
    // decided in the meantime. Focus must re-read without a manual refresh.
    vi.mocked(getKycStatusV1SettingsKycGet)
      .mockResolvedValueOnce(
        ok({ kyc_status: "pending", documents: [submittedDocument()] }),
      )
      .mockResolvedValue(ok({ kyc_status: "verified", documents: [] }));

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.getByText(/verification in review/i)).toBeInTheDocument();
    });

    fireEvent.focus(window);

    await waitFor(() => {
      expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    });
  });

  it("lets a rejected user submit another document", async () => {
    // Rejection is usually a correctable problem (an unreadable photo), so it
    // must never lock the user out of trying again.
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({
        kyc_status: "rejected",
        documents: [submittedDocument({ status: "rejected" })],
      }),
    );

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.getByText(/didn't pass/i)).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /submit for review/i }),
    ).toBeInTheDocument();
  });

  it("shows the verified state and hides the upload form when verified", async () => {
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({ kyc_status: "verified", documents: [] }),
    );

    render(<KycUpload />);

    await waitFor(() => {
      expect(screen.queryByTestId("loading")).not.toBeInTheDocument();
    });

    expect(screen.getByText(/identity verified/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /submit for review/i }),
    ).not.toBeInTheDocument();
  });

  it("tells the user when a submitted document failed the virus scan", async () => {
    // A quarantined document will never reach a reviewer, so the user must be
    // told to replace it rather than left waiting on a decision.
    vi.mocked(getKycStatusV1SettingsKycGet).mockResolvedValue(
      ok({
        kyc_status: "pending",
        documents: [submittedDocument({ scan_status: "quarantined" })],
      }),
    );

    render(<KycUpload />);

    await waitFor(() => {
      expect(
        screen.getByText(/could not be processed/i),
      ).toBeInTheDocument();
    });
  });
});
