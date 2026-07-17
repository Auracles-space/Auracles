import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getReportRubric } from "@/lib/generated/sdk.gen";
import { ReportRubricPanel } from "./report-rubric-panel";

vi.mock("@/lib/generated/sdk.gen", () => ({
  getReportRubric: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

describe("ReportRubricPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the attestor's rubric label, score, and comment", async () => {
    vi.mocked(getReportRubric).mockResolvedValue({
      data: {
        scores: [
          {
            dimension_key: "rigor",
            label: "Methodological rigor",
            score: 4,
            comment: "Sound methodology with minor gaps.",
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<ReportRubricPanel attestationId="att-1" />);

    expect(await screen.findByText("Methodological rigor")).toBeInTheDocument();
    expect(screen.getByText("4 / 5")).toBeInTheDocument();
    expect(
      screen.getByText(/Sound methodology with minor gaps/i),
    ).toBeInTheDocument();
  });

  it("renders nothing when no rubric is available", async () => {
    vi.mocked(getReportRubric).mockResolvedValue({
      data: { scores: [] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    const { container } = render(<ReportRubricPanel attestationId="att-1" />);

    // Wait for the loading spinner to resolve to the empty (null) render.
    await vi.waitFor(() =>
      expect(container.textContent).not.toMatch(/Loading scorecard/i),
    );
    expect(container.textContent).toBe("");
  });
});
