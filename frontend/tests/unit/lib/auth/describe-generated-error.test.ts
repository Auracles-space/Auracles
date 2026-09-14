/**
 * Tests for describeGeneratedError copy resolution.
 *
 * Covers the three error shapes the generated client surfaces: a handler-raised
 * HTTPException (string detail), a Pydantic 422 (array of error entries), and
 * the org routes' structured `{ error_code, message }` dict detail.
 */
import { describe, expect, it } from "vitest";

import { describeGeneratedError } from "@/lib/auth/form-client";

describe("describeGeneratedError", () => {
  it("returns the message for a string detail", () => {
    expect(describeGeneratedError({ detail: "Email already registered." })).toBe(
      "Email already registered.",
    );
  });

  it("joins messages from a Pydantic 422 array detail", () => {
    const error = {
      detail: [
        {
          type: "value_error",
          loc: ["body", "password"],
          msg: "Value error, Password must include at least one digit.",
        },
      ],
    };

    expect(describeGeneratedError(error)).toBe(
      "Value error, Password must include at least one digit.",
    );
  });

  it("prefers the message of a structured dict detail", () => {
    expect(
      describeGeneratedError({
        detail: { error_code: "org_suspended", message: "This organization is suspended." },
      }),
    ).toBe("This organization is suspended.");
  });

  it("humanises a dict detail's error_code when no message is present", () => {
    expect(describeGeneratedError({ detail: { error_code: "step_up_required" } })).toBe(
      "Step up required",
    );
  });

  it("falls back to generic copy for a dict detail with neither field", () => {
    expect(describeGeneratedError({ detail: { code: 42 } })).toBe(
      "The request could not be completed.",
    );
  });

  it("falls back to generic copy for an unknown shape", () => {
    expect(describeGeneratedError({ foo: "bar" })).toBe(
      "The request could not be completed.",
    );
  });
});
