/**
 * Tests for describeGeneratedError copy resolution.
 *
 * Covers the two error shapes the generated client surfaces: a handler-raised
 * HTTPException (string detail) and a Pydantic 422 (array of error entries).
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

  it("falls back to generic copy for an unknown shape", () => {
    expect(describeGeneratedError({ foo: "bar" })).toBe(
      "The request could not be completed.",
    );
  });
});
