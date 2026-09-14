import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { upsertRubricScore, listRubricScores } from "@/lib/generated/sdk.gen";
import { RubricPanel } from "./rubric-panel";

vi.mock("@/lib/generated/sdk.gen", () => ({
  upsertRubricScore: vi.fn(),
  listRubricScores: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer member" }),
}));

/** The rubric the API serves for the workspace's review type. */
const DIMENSIONS = [
  { key: "completeness", label: "Completeness", weight: 0.5, display_order: 0 },
];

/** Resolve the rubric fetch with the served dimensions and saved score rows. */
function mockSavedScores(
  scores: Array<Record<string, unknown>>,
  dimensions: Array<Record<string, unknown>> = DIMENSIONS,
) {
  vi.mocked(listRubricScores).mockResolvedValue({
    response: { ok: true },
    data: { dimensions, scores },
  } as never);
}

describe("RubricPanel rubric source", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the dimensions the API serves, in order", async () => {
    mockSavedScores([], [
      { key: "b", label: "Second", weight: 0.5, display_order: 1 },
      { key: "a", label: "First", weight: 0.5, display_order: 0 },
    ]);

    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    const headings = await screen.findAllByRole("heading", { level: 3 });
    expect(headings).toHaveLength(2);
    expect(headings[0]).toHaveTextContent("First");
    expect(headings[1]).toHaveTextContent("Second");
  });

  it("explains an empty rubric instead of rendering nothing", async () => {
    mockSavedScores([], []);

    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    expect(
      await screen.findByText(/No rubric dimensions configured/i),
    ).toBeInTheDocument();
  });
});

describe("RubricPanel autosave", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSavedScores([]);
    vi.mocked(upsertRubricScore).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);
  });

  it("persists a score even before a comment is entered", async () => {
    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    fireEvent.click(await screen.findByRole("button", { name: "3" }));

    await waitFor(() =>
      expect(vi.mocked(upsertRubricScore)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1", dimension_key: "completeness" },
          body: expect.objectContaining({ score: 3 }),
        }),
      ),
    );
  });

  it("persists a comment even before a score is chosen", async () => {
    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    const comment = await screen.findByPlaceholderText(/Provide justification/i);
    fireEvent.change(comment, { target: { value: "Solid coverage overall." } });
    fireEvent.blur(comment);

    await waitFor(() =>
      expect(vi.mocked(upsertRubricScore)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1", dimension_key: "completeness" },
          body: expect.objectContaining({ comment: "Solid coverage overall." }),
        }),
      ),
    );
  });

  it("does not save an empty dimension on blur", async () => {
    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    const comment = await screen.findByPlaceholderText(/Provide justification/i);
    fireEvent.blur(comment);

    expect(vi.mocked(upsertRubricScore)).not.toHaveBeenCalled();
  });

  it("hydrates saved scores on mount so a reload shows them", async () => {
    mockSavedScores([
      { dimension_key: "completeness", score: 4, comment: "Thorough coverage." },
    ]);

    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    // The saved comment is shown, and the saved score button is selected.
    expect(
      await screen.findByDisplayValue("Thorough coverage."),
    ).toBeInTheDocument();
    const fourButton = screen.getByRole("button", { name: "4" });
    expect(fourButton.className).toContain("bg-accent");
  });
});
