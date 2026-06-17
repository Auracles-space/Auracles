import { describe, expect, it } from "vitest";

import { formatFrameworkStatus } from "@/lib/marketplace/format";

describe("formatFrameworkStatus", () => {
  it("maps workflow statuses to plain contributor-facing labels", () => {
    expect(formatFrameworkStatus("draft")).toBe("Draft");
    expect(formatFrameworkStatus("processing")).toBe("Checking…");
    expect(formatFrameworkStatus("submitted")).toBe("Submitted");
    expect(formatFrameworkStatus("pipeline_passed")).toBe("Ready to publish");
    expect(formatFrameworkStatus("pipeline_failed")).toBe("Checks failed");
    expect(formatFrameworkStatus("published")).toBe("Published");
    expect(formatFrameworkStatus("unpublished")).toBe("Unpublished");
  });

  it("falls back to title-case for unknown values", () => {
    expect(formatFrameworkStatus("some_new_state")).toBe("Some New State");
    expect(formatFrameworkStatus(null)).toBe("Not set");
  });
});
