import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getAttestorTrialV1OrgsOrgIdAttestorTrialGet as getAttestorTrial,
  submitAttestorTrialV1OrgsOrgIdAttestorTrialSubmitPost as submitAttestorTrial,
} from "@/lib/generated/sdk.gen";
import { TrialWorkspace } from "./trial-workspace";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer member" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAttestorTrialV1OrgsOrgIdAttestorTrialGet: vi.fn(),
  submitAttestorTrialV1OrgsOrgIdAttestorTrialSubmitPost: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://test.local"),
  response: new Response(null, { status: 200 }),
});

const err = (status: number) => ({
  data: undefined,
  error: { detail: "nope" },
  request: new Request("http://test.local"),
  response: new Response(null, { status }),
});

describe("TrialWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("gates submit until every dimension is scored and then switches to under review", async () => {
    vi.mocked(getAttestorTrial).mockResolvedValue(
      ok({
        trial_id: "trial-1",
        status: "assigned",
        framework_name: "Calibration Fixture",
        framework_summary: "Review this known-good framework.",
        artifacts: [
          {
            name: "Fixture PDF",
            mime_type: "application/pdf",
            url: "https://example.com/fixture.pdf",
          },
        ],
        dimensions: [
          {
            dimension_id: "dim-1",
            key: "governance",
            label: "Governance",
            display_order: 1,
          },
          {
            dimension_id: "dim-2",
            key: "controls",
            label: "Controls",
            display_order: 2,
          },
        ],
        saved_scores: [],
        feedback: null,
      }) as never,
    );
    vi.mocked(submitAttestorTrial).mockResolvedValue(
      ok({
        trial_id: "trial-1",
        status: "submitted",
        framework_name: "Calibration Fixture",
        framework_summary: "Review this known-good framework.",
        artifacts: [],
        dimensions: [
          {
            dimension_id: "dim-1",
            key: "governance",
            label: "Governance",
            display_order: 1,
          },
          {
            dimension_id: "dim-2",
            key: "controls",
            label: "Controls",
            display_order: 2,
          },
        ],
        saved_scores: [
          { dimension_id: "dim-1", score: 4, comment: "Well reasoned." },
          { dimension_id: "dim-2", score: 5, comment: "Strong evidence." },
        ],
        feedback: null,
      }) as never,
    );

    render(<TrialWorkspace orgId="org-1" />);

    await waitFor(() => expect(screen.getByText(/Calibration Fixture/i)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Fixture PDF/i })).toHaveAttribute(
      "href",
      "https://example.com/fixture.pdf",
    );

    const submit = screen.getByRole("button", { name: /Submit Trial/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Governance score/i), {
      target: { value: "4" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Controls score/i), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByLabelText(/Governance comment/i), {
      target: { value: "Well reasoned." },
    });
    fireEvent.change(screen.getByLabelText(/Controls comment/i), {
      target: { value: "Strong evidence." },
    });

    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);

    await waitFor(() =>
      expect(vi.mocked(submitAttestorTrial)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: {
            scores: [
              { dimension_id: "dim-1", score: 4, comment: "Well reasoned." },
              { dimension_id: "dim-2", score: 5, comment: "Strong evidence." },
            ],
          },
        }),
      ),
    );
    // Waiting on an admin is always "In review" in the shared vocabulary.
    expect(await screen.findByText("In review")).toBeInTheDocument();
    expect(screen.queryByText(/Under review/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Submit Trial/i })).not.toBeInTheDocument();
  });

  it("explains how a trial reaches a member who has none on 404", async () => {
    vi.mocked(getAttestorTrial).mockResolvedValue(err(404) as never);
    render(<TrialWorkspace orgId="org-1" />);
    expect(
      await screen.findByText(/No calibration trial is assigned to you/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No active trial assigned/i)).toBeNull();
  });

  it("tells a nominee their trial opens once an administrator starts it", async () => {
    vi.mocked(getAttestorTrial).mockResolvedValue({
      data: undefined,
      error: { detail: { error_code: "trial_not_started", message: "Nominated." } },
      response: { ok: false, status: 404 },
    } as never);
    render(<TrialWorkspace orgId="org-1" />);
    expect(
      await screen.findByText(/nominated for your organization's calibration trial/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/administrator starts/i)).toBeInTheDocument();
  });

  it("explains a trial assigned to another member on 403", async () => {
    vi.mocked(getAttestorTrial).mockResolvedValue(err(403) as never);
    render(<TrialWorkspace orgId="org-1" />);
    expect(
      await screen.findByText(/assigned to another member/i),
    ).toBeInTheDocument();
  });

  it("renders the terminal outcome and feedback without a submit form", async () => {
    vi.mocked(getAttestorTrial).mockResolvedValue(
      ok({
        trial_id: "trial-1",
        status: "passed",
        framework_name: "Calibration Fixture",
        framework_summary: "Review this known-good framework.",
        artifacts: [],
        dimensions: [
          { dimension_id: "dim-1", key: "governance", label: "Governance", display_order: 1 },
        ],
        saved_scores: [{ dimension_id: "dim-1", score: 4, comment: "Solid." }],
        feedback: "Strong calibration — approved.",
      }) as never,
    );
    render(<TrialWorkspace orgId="org-1" />);

    const pill = await screen.findByText("Passed");
    expect(pill.className).toContain("text-success");
    expect(screen.getByText(/Strong calibration — approved\./i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Submit Trial/i })).not.toBeInTheDocument();
  });
});
