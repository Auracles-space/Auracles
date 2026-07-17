/**
 * Regression tests for the attestor report submission panel.
 *
 * Verifies that evidence uploads are submitted using the backend contract's
 * `evidence_references.file_keys` shape.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createAttestationEvidenceUpload,
  submitAttestationReport,
} from "@/lib/generated/sdk.gen";
import { ReportPanel } from "./report-panel";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer member" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createAttestationEvidenceUpload: vi.fn(),
  submitAttestationReport: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://test.local"),
  response: new Response(null, { status: 200 }),
});

describe("ReportPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    vi.stubGlobal("alert", vi.fn());
  });

  const validSummary = "This review summary is long enough for submission.";
  const validScope = "Reviewed the framework artifacts and supporting notes.";

  function summaryInput(): HTMLElement {
    return screen.getByPlaceholderText(
      /This framework demonstrates excellent compliance with/i,
    );
  }
  function scopeInput(): HTMLElement {
    return screen.getByPlaceholderText(
      /Review covered version 2\.1 of the framework/i,
    );
  }

  it("keeps submit disabled until required fields meet their minimums", () => {
    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);
    const submit = screen.getByRole("button", { name: /Submit Report/i });

    // Nothing filled.
    expect(submit).toBeDisabled();

    // Outcome + a too-short summary must not enable submit (backend min 20).
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(summaryInput(), { target: { value: "too short" } });
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    expect(submit).toBeDisabled();

    // A summary that clears the minimum enables submit.
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    expect(submit).toBeEnabled();
  });

  it("requires conditions when the outcome is conditional", () => {
    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);
    const submit = screen.getByRole("button", { name: /Submit Report/i });

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "conditional" },
    });
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    // Conditional with no conditions text stays disabled.
    expect(submit).toBeDisabled();

    fireEvent.change(
      screen.getByPlaceholderText(/must be met for full approval/i),
      { target: { value: "Must add SOC2 mapping before full approval." } },
    );
    expect(submit).toBeEnabled();
  });

  it("submits uploaded evidence as file_keys", async () => {
    vi.mocked(createAttestationEvidenceUpload).mockResolvedValue(
      ok({
        id: "upload-session-1",
        s3_key: "attestations/att-1/evidence/member-1/report.pdf",
        url: "https://uploads.example.test",
        fields: { key: "attestations/att-1/evidence/member-1/report.pdf" },
        expires_at: "2026-07-17T12:00:00Z",
        size_limit: 26214400,
        scan_status: "pending_scan",
      }) as never,
    );
    vi.mocked(submitAttestationReport).mockResolvedValue(
      ok({ id: "att-1", status: "report_submitted" }) as never,
    );

    const { container } = render(
      <ReportPanel
        attestationId="att-1"
        canWrite
        orgId="org-1"
      />,
    );

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(
      screen.getByPlaceholderText(
        /This framework demonstrates excellent compliance with/i,
      ),
      {
        target: { value: "This review summary is long enough for submission." },
      },
    );
    fireEvent.change(
      screen.getByPlaceholderText(/Review covered version 2\.1 of the framework/i),
      {
        target: { value: "Reviewed the framework artifacts and supporting notes." },
      },
    );

    const file = new File(["evidence"], "report.pdf", {
      type: "application/pdf",
    });
    const fileInput = container.querySelector('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput as HTMLInputElement, {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Submit Report/i }));

    await waitFor(() =>
      expect(vi.mocked(submitAttestationReport)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1" },
          body: expect.objectContaining({
            evidence_references: {
              file_keys: ["attestations/att-1/evidence/member-1/report.pdf"],
            },
          }),
        }),
      ),
    );
  });
});
