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

vi.mock("./rubrics", () => ({
  RUBRICS: {
    quality: [{ key: "completeness", label: "Completeness", weight: 0.5 }],
  },
}));

/** Resolve the saved-score fetch with the given score rows. */
function mockSavedScores(scores: Array<Record<string, unknown>>) {
  vi.mocked(listRubricScores).mockResolvedValue({
    response: { ok: true },
    data: { scores },
  } as never);
}

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
