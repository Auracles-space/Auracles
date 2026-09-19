import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CredentialForm } from "@/components/modules/attestation/credential-form";
import {
  confirmCredentialEvidenceUpload,
  createCredentialEvidenceUploadSessionV1CredentialsCredentialIdUploadsPost as createUploadSession,
  getCredentialEvidenceUpload,
} from "@/lib/generated/sdk.gen";
import type { CredentialResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createCredentialEvidenceUploadSessionV1CredentialsCredentialIdUploadsPost:
    vi.fn(),
  confirmCredentialEvidenceUpload: vi.fn(),
  getCredentialEvidenceUpload: vi.fn(),
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
  it("renders placeholders for the free-text credential fields", () => {
    render(
      <CredentialForm
        mode="create"
        onSubmit={vi.fn()}
        submitting={false}
      />,
    );

    expect(screen.getByPlaceholderText("e.g. Project Management Professional")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("e.g. Project Management Institute")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("e.g. PMP-2026-001245")).toBeInTheDocument();
    expect(screen.getByText("Credential title")).toBeInTheDocument();
    expect(screen.getByText("Issuer")).toBeInTheDocument();
    expect(screen.getByText("Issued date")).toBeInTheDocument();
    expect(screen.getAllByText("*")).toHaveLength(3);
  });

  it("shows a disabled upload placeholder and save-first guidance in create mode", () => {
    render(
      <CredentialForm
        mode="create"
        onSubmit={vi.fn()}
        submitting={false}
      />,
    );

    expect(screen.getByLabelText("Upload evidence")).toBeDisabled();
    expect(
      screen.getByText("Upload is available after the first save."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Save the credential once to unlock evidence upload."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("PDF, Word, and image files up to 10 MB."),
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

  it("rejects files larger than 10 MB before upload starts", async () => {
    render(
      <CredentialForm
        initial={existing}
        mode="edit"
        onSubmit={vi.fn()}
        submitting={false}
      />,
    );

    const input = screen.getByLabelText("Upload evidence");
    const oversizedFile = new File(["x"], "evidence.pdf", {
      type: "application/pdf",
    });
    Object.defineProperty(oversizedFile, "size", {
      configurable: true,
      value: 10 * 1024 * 1024 + 1,
    });

    fireEvent.change(input, { target: { files: [oversizedFile] } });

    await waitFor(() => {
      expect(
        screen.getByText("Evidence files must be 10 MB or smaller."),
      ).toBeInTheDocument();
    });
  });

  it("confirms the upload and attaches the file only once it scans clean", async () => {
    // Nothing used to tell the API the file had landed, so the scan only began
    // inside the save that then refused the evidence it was scanning.
    const ok = <T,>(data: T) => ({
      data,
      error: undefined,
      request: new Request("http://test.local"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(createUploadSession).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "credentials/c1/licence.pdf",
        url: "https://uploads.example.test",
        fields: { key: "credentials/c1/licence.pdf" },
        expires_at: "2026-09-19T12:00:00Z",
        size_limit: 10485760,
        scan_status: "pending_scan",
      }) as never,
    );
    vi.mocked(confirmCredentialEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "credentials/c1/licence.pdf",
        scan_status: "pending_scan",
      }) as never,
    );
    vi.mocked(getCredentialEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "credentials/c1/licence.pdf",
        scan_status: "clean",
      }) as never,
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));

    render(
      <CredentialForm
        initial={existing}
        mode="edit"
        onSubmit={vi.fn()}
        scanPollIntervalMs={1}
        submitting={false}
      />,
    );

    fireEvent.change(screen.getByLabelText("Upload evidence"), {
      target: {
        files: [new File(["x"], "licence.pdf", { type: "application/pdf" })],
      },
    });

    await waitFor(() =>
      expect(screen.getByText("licence.pdf")).toBeInTheDocument(),
    );
    expect(confirmCredentialEvidenceUpload).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { credential_id: existing.id, upload_session_id: "session-1" },
      }),
    );
  });

  it("refuses to attach a file that fails its virus check", async () => {
    const ok = <T,>(data: T) => ({
      data,
      error: undefined,
      request: new Request("http://test.local"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(createUploadSession).mockResolvedValue(
      ok({
        id: "session-2",
        s3_key: "credentials/c1/bad.pdf",
        url: "https://uploads.example.test",
        fields: { key: "credentials/c1/bad.pdf" },
        expires_at: "2026-09-19T12:00:00Z",
        size_limit: 10485760,
        scan_status: "pending_scan",
      }) as never,
    );
    vi.mocked(confirmCredentialEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-2",
        s3_key: "credentials/c1/bad.pdf",
        scan_status: "pending_scan",
      }) as never,
    );
    vi.mocked(getCredentialEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-2",
        s3_key: "credentials/c1/bad.pdf",
        scan_status: "infected",
      }) as never,
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));

    render(
      <CredentialForm
        initial={existing}
        mode="edit"
        onSubmit={vi.fn()}
        scanPollIntervalMs={1}
        submitting={false}
      />,
    );

    fireEvent.change(screen.getByLabelText("Upload evidence"), {
      target: {
        files: [new File(["x"], "bad.pdf", { type: "application/pdf" })],
      },
    });

    await waitFor(() =>
      expect(
        screen.getByText(/did not pass the virus check/i),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("bad.pdf")).toBeNull();
  });
});
