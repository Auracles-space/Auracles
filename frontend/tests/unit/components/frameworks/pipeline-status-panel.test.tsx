import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineStatusPanel } from "@/components/modules/frameworks/pipeline-status-panel";
import type { ArtifactResponse } from "@/lib/generated/types.gen";

const baseArtifact: ArtifactResponse = {
  created_at: "2026-06-08T10:00:00Z",
  file_key: "private/frameworks/artifact.pdf",
  file_size: 1024,
  framework_id: "fw_123",
  id: "art_123",
  mime_type: "application/pdf",
  name: "Operating Model.pdf",
  pii_detected: false,
  pii_review_needed: false,
  processing_status: "processed",
  rarity_score: "0.91",
  scan_status: "clean",
};

describe("PipelineStatusPanel", () => {
  it("renders all-green checks when an artifact is clean, processed, and rare enough", () => {
    render(
      <PipelineStatusPanel
        artifacts={[baseArtifact]}
        frameworkStatus="pipeline_passed"
      />,
    );

    expect(screen.getByText("Virus scan")).toBeInTheDocument();
    expect(screen.getByText("Clean")).toBeInTheDocument();
    expect(screen.getByText("PII review")).toBeInTheDocument();
    expect(screen.getByText("No review needed")).toBeInTheDocument();
    expect(screen.getByText("Rarity")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
  });

  it("surfaces PII review as an action-blocking issue", () => {
    render(
      <PipelineStatusPanel
        artifacts={[
          {
            ...baseArtifact,
            pii_detected: true,
            pii_review_needed: true,
            processing_status: "flagged_pii",
          },
        ]}
        frameworkStatus="pipeline_failed"
      />,
    );

    expect(screen.getByText("Review required")).toBeInTheDocument();
    expect(
      screen.getByText(/replace or resolve the flagged artifact/i),
    ).toBeInTheDocument();
  });
});
