/**
 * Tests for the report evidence uploader.
 *
 * Evidence is scanned for viruses before a report may reference it, and the
 * scan only starts once the browser confirms the upload. These tests pin that
 * handshake: upload once, confirm once, wait for the verdict, and never hand
 * the report a file that has not come back clean.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  confirmAttestationEvidenceUpload,
  createAttestationEvidenceUpload,
  getAttestationEvidenceUpload,
} from "@/lib/generated/sdk.gen";
import { ReportEvidenceUploader } from "./report-evidence-uploader";

vi.mock("@/lib/auth/form-client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auth/form-client")>()),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer member" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createAttestationEvidenceUpload: vi.fn(),
  confirmAttestationEvidenceUpload: vi.fn(),
  getAttestationEvidenceUpload: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://test.local"),
  response: new Response(null, { status: 200 }),
});

/** Select one file on the uploader's file input. */
async function selectFile(name = "site-visit.pdf") {
  const input = screen.getByLabelText(/evidence files/i) as HTMLInputElement;
  const file = new File(["evidence"], name, { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

describe("ReportEvidenceUploader", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    vi.mocked(createAttestationEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "attestations/a1/evidence/site-visit.pdf",
        url: "https://uploads.example.test",
        fields: { key: "attestations/a1/evidence/site-visit.pdf" },
        expires_at: new Date().toISOString(),
        size_limit: 26214400,
        scan_status: "pending_scan",
      }) as never,
    );
    vi.mocked(confirmAttestationEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "attestations/a1/evidence/site-visit.pdf",
        scan_status: "pending_scan",
      }) as never,
    );
  });

  it("uploads once, confirms it, and reports the file ready when it scans clean", async () => {
    const onChange = vi.fn();
    vi.mocked(getAttestationEvidenceUpload)
      .mockResolvedValueOnce(
        ok({
          id: "session-1",
          s3_key: "attestations/a1/evidence/site-visit.pdf",
          scan_status: "pending_scan",
        }) as never,
      )
      .mockResolvedValue(
        ok({
          id: "session-1",
          s3_key: "attestations/a1/evidence/site-visit.pdf",
          scan_status: "clean",
        }) as never,
      );

    render(
      <ReportEvidenceUploader
        attestationId="a1"
        onChange={onChange}
        pollIntervalMs={1}
      />,
    );
    await selectFile();

    await waitFor(() =>
      expect(screen.getByText(/checked and ready/i)).toBeInTheDocument(),
    );
    expect(createAttestationEvidenceUpload).toHaveBeenCalledTimes(1);
    expect(confirmAttestationEvidenceUpload).toHaveBeenCalledTimes(1);
    expect(confirmAttestationEvidenceUpload).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { attestation_id: "a1", upload_session_id: "session-1" },
      }),
    );
    // The parent is handed the storage key only once the file is clean.
    expect(onChange).toHaveBeenLastCalledWith({
      fileKeys: ["attestations/a1/evidence/site-visit.pdf"],
      settled: true,
    });
  });

  it("holds the report back while a file is still being checked", async () => {
    const onChange = vi.fn();
    vi.mocked(getAttestationEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "attestations/a1/evidence/site-visit.pdf",
        scan_status: "pending_scan",
      }) as never,
    );

    render(
      <ReportEvidenceUploader
        attestationId="a1"
        onChange={onChange}
        pollIntervalMs={1}
      />,
    );
    await selectFile();

    await waitFor(() =>
      expect(screen.getByText(/checking this file/i)).toBeInTheDocument(),
    );
    expect(onChange).toHaveBeenLastCalledWith({ fileKeys: [], settled: false });
  });

  it("says so when a file fails its virus check, and attaches nothing", async () => {
    const onChange = vi.fn();
    vi.mocked(getAttestationEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "attestations/a1/evidence/site-visit.pdf",
        scan_status: "infected",
      }) as never,
    );

    render(
      <ReportEvidenceUploader
        attestationId="a1"
        onChange={onChange}
        pollIntervalMs={1}
      />,
    );
    await selectFile();

    await waitFor(() =>
      expect(screen.getByText(/did not pass the virus check/i)).toBeInTheDocument(),
    );
    expect(onChange).toHaveBeenLastCalledWith({ fileKeys: [], settled: false });
  });

  it("lets a failed file be removed so the report can go out without it", async () => {
    const onChange = vi.fn();
    vi.mocked(getAttestationEvidenceUpload).mockResolvedValue(
      ok({
        id: "session-1",
        s3_key: "attestations/a1/evidence/site-visit.pdf",
        scan_status: "error",
      }) as never,
    );

    render(
      <ReportEvidenceUploader
        attestationId="a1"
        onChange={onChange}
        pollIntervalMs={1}
      />,
    );
    await selectFile();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: /remove/i }));

    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith({ fileKeys: [], settled: true }),
    );
    expect(screen.queryByText("site-visit.pdf")).toBeNull();
  });
});
