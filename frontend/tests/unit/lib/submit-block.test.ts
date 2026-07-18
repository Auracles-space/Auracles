import { describe, expect, it } from "vitest";

import { deriveSubmitBlock } from "@/lib/frameworks/submit-block";
import type { ArtifactResponse } from "@/lib/generated/types.gen";

/** Build an ArtifactResponse fixture with clean, processed defaults. */
function artifact(overrides: Partial<ArtifactResponse> = {}): ArtifactResponse {
  return {
    id: "artifact-1",
    framework_id: "framework-1",
    name: "playbook.docx",
    file_key: "key",
    file_size: 1024,
    mime_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    source_kind: "upload",
    scan_status: "clean",
    processing_status: "processed",
    pii_detected: false,
    pii_review_needed: false,
    redaction_available: false,
    redaction_status: null,
    redaction_accepted: false,
    near_duplicate_blocked: false,
    rarity_score: "0.5",
    created_at: "2026-07-18T09:00:00Z",
    ...overrides,
  } as ArtifactResponse;
}

describe("deriveSubmitBlock", () => {
  it("does not block a clean, processed artifact", () => {
    const block = deriveSubmitBlock([artifact()]);
    expect(block.hardBlocked).toBe(false);
    expect(block.reasons).toEqual([]);
  });

  it("hard-blocks a near-duplicate artifact", () => {
    const block = deriveSubmitBlock([
      artifact({ near_duplicate_blocked: true }),
    ]);
    expect(block.hardBlocked).toBe(true);
    expect(block.reasons.map((reason) => reason.code)).toContain(
      "near_duplicate",
    );
  });

  it("hard-blocks an infected artifact", () => {
    const block = deriveSubmitBlock([artifact({ scan_status: "infected" })]);
    expect(block.hardBlocked).toBe(true);
    expect(block.reasons.map((reason) => reason.code)).toContain("virus");
  });

  it("hard-blocks an artifact awaiting PII review", () => {
    const block = deriveSubmitBlock([artifact({ pii_review_needed: true })]);
    expect(block.hardBlocked).toBe(true);
    expect(block.reasons.map((reason) => reason.code)).toContain("pii");
  });

  it("hard-blocks an artifact whose processing failed", () => {
    const block = deriveSubmitBlock([
      artifact({ processing_status: "failed" }),
    ]);
    expect(block.hardBlocked).toBe(true);
    expect(block.reasons.map((reason) => reason.code)).toContain("processing");
  });

  it("reports each distinct reason once across artifacts", () => {
    const block = deriveSubmitBlock([
      artifact({ id: "a", near_duplicate_blocked: true }),
      artifact({ id: "b", near_duplicate_blocked: true }),
      artifact({ id: "c", pii_review_needed: true }),
    ]);
    expect(block.reasons.map((reason) => reason.code).sort()).toEqual([
      "near_duplicate",
      "pii",
    ]);
  });
});
