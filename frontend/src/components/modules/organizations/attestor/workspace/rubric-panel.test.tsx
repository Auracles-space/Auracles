import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { upsertRubricScore } from "@/lib/generated/sdk.gen";
import { RubricPanel } from "./rubric-panel";

vi.mock("@/lib/generated/sdk.gen", () => ({
  upsertRubricScore: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer member" }),
}));

vi.mock("./rubrics", () => ({
  RUBRICS: {
    quality: [{ key: "completeness", label: "Completeness", weight: 0.5 }],
  },
}));

describe("RubricPanel autosave", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(upsertRubricScore).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);
  });

  it("persists a score even before a comment is entered", async () => {
    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    fireEvent.click(screen.getByRole("button", { name: "3" }));

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

    const comment = screen.getByPlaceholderText(/Provide justification/i);
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

  it("does not save an empty dimension on blur", () => {
    render(<RubricPanel attestationId="att-1" reviewType="quality" canWrite />);

    const comment = screen.getByPlaceholderText(/Provide justification/i);
    fireEvent.blur(comment);

    expect(vi.mocked(upsertRubricScore)).not.toHaveBeenCalled();
  });
});
