import { describe, it, expect } from "vitest";
import { describeGeneratedError } from "./form-client";

describe("describeGeneratedError", () => {
  it("returns a plain string detail", () => {
    expect(describeGeneratedError({ detail: "Attestation not found." })).toBe(
      "Attestation not found.",
    );
  });

  it("joins Pydantic detail entries", () => {
    expect(
      describeGeneratedError({
        detail: [{ msg: "field required", loc: ["body", "summary"] }],
      }),
    ).toBe("field required");
  });

  it("joins a list of plain-string failures (quality gate shape)", () => {
    // The report quality gate returns detail as a list of human-readable
    // strings, not Pydantic {msg} objects. Each must be surfaced.
    expect(
      describeGeneratedError({
        detail: [
          "Rubric dimension 'Accuracy' needs a score and comment.",
          "Resolve the open clarification before submitting.",
        ],
      }),
    ).toBe(
      "Rubric dimension 'Accuracy' needs a score and comment. " +
        "Resolve the open clarification before submitting.",
    );
  });

  it("falls back for an unrecognized shape", () => {
    expect(describeGeneratedError({})).toBe(
      "The request could not be completed.",
    );
  });
});
