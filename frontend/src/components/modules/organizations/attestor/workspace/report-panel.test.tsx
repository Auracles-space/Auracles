/**
 * Regression tests for the attestor report submission panel.
 *
 * Verifies that evidence uploads are submitted using the backend contract's
 * `evidence_references.file_keys` shape.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getAttestationReportDraft,
  listRubricScores,
  saveAttestationReportDraft,
  submitAttestationReport,
} from "@/lib/generated/sdk.gen";
import { RUBRIC_SAVED_EVENT } from "@/lib/attestation/workspace-events";
import { ReportPanel } from "./report-panel";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

vi.mock("@/lib/auth/form-client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auth/form-client")>()),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer member" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAttestationReportDraft: vi.fn(),
  listRubricScores: vi.fn(),
  saveAttestationReportDraft: vi.fn(),
  submitAttestationReport: vi.fn(),
}));

// The uploader owns the upload-confirm-scan handshake and is covered by its
// own tests; here it stands in as a switch so the panel's gating is testable.
vi.mock("./report-evidence-uploader", () => ({
  ReportEvidenceUploader: ({
    onChange,
  }: {
    onChange: (selection: { fileKeys: string[]; settled: boolean }) => void;
  }) => (
    <div>
      <button
        type="button"
        onClick={() => onChange({ fileKeys: [], settled: false })}
      >
        stub-scanning
      </button>
      <button
        type="button"
        onClick={() =>
          onChange({ fileKeys: ["attestations/att-1/evidence/report.pdf"], settled: true })
        }
      >
        stub-clean
      </button>
    </div>
  ),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://test.local"),
  response: new Response(null, { status: 200 }),
});

/** Build a rubric-scores response whose comments sum to `words` words. */
const rubricWithWords = (words: number) =>
  ok({
    scores: [
      {
        dimension_key: "rigor",
        score: 4,
        comment: Array.from({ length: words }, () => "word").join(" "),
      },
    ],
  });

describe("ReportPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    vi.stubGlobal("alert", vi.fn());
    // Default: rubric comments already clear the 150-word report minimum, so
    // the field-level minimum tests stay focused on their own assertions.
    vi.mocked(listRubricScores).mockResolvedValue(rubricWithWords(200) as never);
    // Default: nothing written yet, so the form starts empty.
    vi.mocked(getAttestationReportDraft).mockResolvedValue(
      ok({
        outcome: null,
        summary: "",
        scope: "",
        conditions: "",
        updated_at: null,
      }) as never,
    );
    vi.mocked(saveAttestationReportDraft).mockResolvedValue(
      ok({
        outcome: null,
        summary: "",
        scope: "",
        conditions: "",
        updated_at: "2026-09-18T10:00:00Z",
      }) as never,
    );
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

  it("keeps submit disabled until the required fields are present", async () => {
    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);
    const submit = screen.getByRole("button", { name: /Submit Report/i });

    // Nothing filled.
    expect(submit).toBeDisabled();

    // Outcome + summary but no scope must not enable submit (scope required).
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    expect(submit).toBeDisabled();

    // With every required field present and the word gate satisfied (rubric
    // words from the mocked fetch), submit enables.
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("keeps submit disabled until the report reaches the minimum word count", async () => {
    // Rubric comments contribute only a handful of words, so summary + rubric
    // stay under the 150-word report minimum until the summary is long enough.
    vi.mocked(listRubricScores).mockResolvedValue(rubricWithWords(5) as never);
    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);
    const submit = screen.getByRole("button", { name: /Submit Report/i });

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    // Field minimums met, but total words well under 150 → still disabled.
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    await waitFor(() => expect(screen.getByText(/\/ 150 words/i)).toBeInTheDocument());
    expect(submit).toBeDisabled();

    // A summary long enough to clear the remaining words enables submit.
    const longSummary = Array.from({ length: 160 }, () => "finding").join(" ");
    fireEvent.change(summaryInput(), { target: { value: longSummary } });
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("recounts rubric comment words when a rubric score is saved", async () => {
    // The count was read once on mount, so comments saved afterwards never
    // reached it and the report stayed "too short" until a reload.
    vi.mocked(listRubricScores)
      .mockResolvedValueOnce(rubricWithWords(0) as never)
      .mockResolvedValue(rubricWithWords(160) as never);

    render(
      <ReportPanel attestationId="att-1" canWrite orgId="org-1" status="in_review" />,
    );
    expect(await screen.findByText(/Rubric comments 0 \+/)).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new Event(RUBRIC_SAVED_EVENT));
    });

    expect(await screen.findByText(/Rubric comments 160 \+/)).toBeInTheDocument();
  });

  it("requires conditions when the outcome is conditional", async () => {
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
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("shows a submitted state instead of the form once the report is in", () => {
    render(
      <ReportPanel
        attestationId="att-1"
        canWrite
        orgId="org-1"
        status="report_submitted"
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Submit Report/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Your report is with the requestor/i),
    ).toBeInTheDocument();
  });

  it("explains that an admin is handling a disputed report", () => {
    render(
      <ReportPanel attestationId="att-1" canWrite orgId="org-1" status="disputed" />,
    );

    expect(
      screen.getByText(/The requestor disputed this report/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Submit Report/i }),
    ).not.toBeInTheDocument();
  });

  it("says a settled attestation can no longer be edited", () => {
    render(
      <ReportPanel attestationId="att-1" canWrite orgId="org-1" status="released" />,
    );

    expect(
      screen.getByText(/This attestation is closed/i),
    ).toBeInTheDocument();
  });

  it("reopens the form with revision instructions after a revision request", () => {
    render(
      <ReportPanel
        attestationId="att-1"
        canWrite
        orgId="org-1"
        status="revision_requested"
      />,
    );

    expect(
      screen.getByRole("button", { name: /Submit Report/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/An admin asked for a revision/i),
    ).toBeInTheDocument();
  });

  it("surfaces quality-gate failures returned on submit", async () => {
    vi.mocked(submitAttestationReport).mockResolvedValue({
      data: undefined,
      error: {
        detail: ["Resolve the open clarification before submitting."],
      },
      request: new Request("http://test.local"),
      response: new Response(null, { status: 422 }),
    } as never);

    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    const submit = screen.getByRole("button", { name: /Submit Report/i });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    expect(
      await screen.findByText(/Resolve the open clarification before submitting/i),
    ).toBeInTheDocument();
  });

  it("submits evidence the uploader reported clean as file_keys", async () => {
    vi.mocked(submitAttestationReport).mockResolvedValue(
      ok({ id: "att-1", status: "report_submitted" }) as never,
    );

    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    fireEvent.click(screen.getByRole("button", { name: "stub-clean" }));

    const submit = screen.getByRole("button", { name: /Submit Report/i });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() =>
      expect(vi.mocked(submitAttestationReport)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1" },
          body: expect.objectContaining({
            evidence_references: {
              file_keys: ["attestations/att-1/evidence/report.pdf"],
            },
          }),
        }),
      ),
    );
    // The queue lives under the Attestor tab; the old /queue URL only redirects.
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/dashboard/organizations/org-1/attestor/queue"),
    );
  });

  it("holds submission while an evidence file is still being checked", async () => {
    // Submitting mid-scan was the bug: the backend refused the report and the
    // retry re-uploaded the file, so it could never succeed.
    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "approved" },
    });
    fireEvent.change(summaryInput(), { target: { value: validSummary } });
    fireEvent.change(scopeInput(), { target: { value: validScope } });
    const submit = screen.getByRole("button", { name: /Submit Report/i });
    await waitFor(() => expect(submit).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "stub-scanning" }));

    await waitFor(() => expect(submit).toBeDisabled());
    expect(
      screen.getByText(/Waiting for the evidence check to finish/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "stub-clean" }));
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("restores the saved draft so a refresh does not lose the report", async () => {
    // The report fields used to live only in this component's state, so any
    // refresh sent the reviewer back to a blank form.
    vi.mocked(getAttestationReportDraft).mockResolvedValue(
      ok({
        outcome: "conditional",
        summary: "Controls are sound apart from access review cadence.",
        scope: "Reviewed policy set v2.1.",
        conditions: "Quarterly access reviews must be evidenced.",
        updated_at: "2026-09-18T09:30:00Z",
      }) as never,
    );

    render(<ReportPanel attestationId="att-1" canWrite orgId="org-1" />);

    await waitFor(() =>
      expect(summaryInput()).toHaveValue(
        "Controls are sound apart from access review cadence.",
      ),
    );
    expect(scopeInput()).toHaveValue("Reviewed policy set v2.1.");
    expect(screen.getByRole("combobox")).toHaveValue("conditional");
    expect(
      screen.getByPlaceholderText(/must be met for full approval/i),
    ).toHaveValue("Quarterly access reviews must be evidenced.");
  });

  it("saves the report as it is written", async () => {
    render(
      <ReportPanel
        attestationId="att-1"
        canWrite
        orgId="org-1"
        draftSaveDelayMs={1}
      />,
    );
    await waitFor(() => expect(getAttestationReportDraft).toHaveBeenCalled());

    fireEvent.change(summaryInput(), { target: { value: validSummary } });

    await waitFor(() =>
      expect(saveAttestationReportDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1" },
          body: expect.objectContaining({ summary: validSummary }),
        }),
      ),
    );
    expect(await screen.findByText(/draft saved/i)).toBeInTheDocument();
  });

  it("does not touch the draft once the report is locked", async () => {
    render(
      <ReportPanel
        attestationId="att-1"
        canWrite
        orgId="org-1"
        status="report_submitted"
      />,
    );

    await waitFor(() =>
      expect(screen.getByText(/Your report is with the requestor/i)).toBeInTheDocument(),
    );
    expect(getAttestationReportDraft).not.toHaveBeenCalled();
    expect(saveAttestationReportDraft).not.toHaveBeenCalled();
  });
});
