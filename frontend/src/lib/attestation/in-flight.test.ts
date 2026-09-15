import { describe, expect, it } from "vitest";

import { inFlightAttestationsFor } from "./in-flight";

const base = { target_type: "framework", target_id: "fw-1" };

describe("inFlightAttestationsFor", () => {
  it("returns the framework's requests that are still in progress", () => {
    const result = inFlightAttestationsFor(
      [
        { ...base, id: "a1", status: "offered", review_type: "quality" },
        { ...base, id: "a2", status: "released", review_type: "compliance" },
        { ...base, id: "a3", status: "cancelled", review_type: "expert" },
        { ...base, id: "a4", status: "report_submitted", review_type: "expert" },
        { ...base, target_id: "fw-2", id: "a5", status: "offered", review_type: "provenance" },
      ],
      "fw-1",
    );

    expect(result.map((item) => item.id)).toEqual(["a1", "a4"]);
  });
});
