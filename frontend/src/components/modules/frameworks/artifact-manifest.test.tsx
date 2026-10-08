/**
 * Artifact manifest preview-control tests.
 *
 * The preview control is the only way a Contributor can choose what a shopper
 * sees before buying, and it is hidden rather than disabled when a file is not
 * eligible. QA hit exactly that: files whose PII hold had been cleared by
 * declaring citations showed no control and no reason, so the rule each branch
 * of `canBePreview` encodes is worth pinning down.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ArtifactResponse } from "@/lib/generated/types.gen";
import { ArtifactManifest } from "./artifact-manifest";

vi.mock("@/components/modules/frameworks/source-preview-badge", () => ({
  SourcePreviewBadge: () => null,
}));

/** Build a processed, preview-clean artifact, overridden per case. */
function artifact(overrides: Partial<ArtifactResponse> = {}): ArtifactResponse {
  return {
    id: "artifact-1",
    framework_id: "framework-1",
    name: "01-founders-agreement.pdf",
    file_key: "frameworks/framework-1/artifacts/artifact-1/file.pdf",
    file_size: 20480,
    mime_type: "application/pdf",
    source_kind: "upload",
    scan_status: "clean",
    processing_status: "processed",
    pii_detected: false,
    pii_review_needed: false,
    pii_types_found: [],
    redaction_available: false,
    redaction_status: null,
    redaction_accepted: false,
    pii_override_accepted: false,
    rarity_score: null,
    near_duplicate_blocked: false,
    similarity_notice: null,
    created_at: "2026-10-08T00:00:00Z",
    ...overrides,
  } as ArtifactResponse;
}

/** Render the manifest for one artifact on a draft Framework. */
function renderManifest(subject: ArtifactResponse) {
  render(
    <ArtifactManifest
      artifacts={[subject]}
      canRemove
      frameworkId="framework-1"
      frameworkStatus="draft"
      onPreviewSet={vi.fn()}
      onRemove={vi.fn()}
      previewArtifactId={null}
      setPreviewArtifact={vi.fn()}
    />,
  );
}

describe("ArtifactManifest preview control", () => {
  it("offers a clean processed file as the preview", () => {
    renderManifest(artifact());

    expect(screen.getByRole("button", { name: "Set as preview" })).toBeTruthy();
  });

  it("offers a file whose PII hold the owner cleared as citations", () => {
    renderManifest(
      artifact({ pii_detected: true, pii_override_accepted: true }),
    );

    expect(screen.getByRole("button", { name: "Set as preview" })).toBeTruthy();
  });

  it("offers a file whose generated redaction the owner accepted", () => {
    renderManifest(artifact({ pii_detected: true, redaction_accepted: true }));

    expect(screen.getByRole("button", { name: "Set as preview" })).toBeTruthy();
  });

  it("withholds a file still held for PII review", () => {
    renderManifest(artifact({ pii_detected: true, pii_review_needed: true }));

    expect(screen.queryByRole("button", { name: "Set as preview" })).toBeNull();
  });

  it("withholds a file whose PII is neither redacted nor declared", () => {
    renderManifest(artifact({ pii_detected: true }));

    expect(screen.queryByRole("button", { name: "Set as preview" })).toBeNull();
  });
});
