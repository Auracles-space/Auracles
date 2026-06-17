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
  near_duplicate_blocked: false,
  redaction_accepted: false,
  redaction_available: false,
  redaction_status: null,
  scan_status: "clean",
  similarity_notice: null,
};

describe("PipelineStatusPanel", () => {
  it("shows a neutral not-started state before any artifact is uploaded", () => {
    render(
      <PipelineStatusPanel
        artifacts={[]}
        frameworkId="fw_123"
        frameworkStatus="draft"
      />,
    );

    expect(screen.getByText("Virus scan")).toBeInTheDocument();
    // Nothing is queued yet, so no gate reads as the in-progress "Pending".
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not started")).toHaveLength(3);
  });

  it("renders all-green checks when an artifact is clean, processed, and rare enough", () => {
    render(
      <PipelineStatusPanel
        artifacts={[baseArtifact]}
        frameworkId="fw_123"
        frameworkStatus="pipeline_passed"
      />,
    );

    expect(screen.getByText("Virus scan")).toBeInTheDocument();
    expect(screen.getByText("Clean")).toBeInTheDocument();
    expect(screen.getByText("PII review")).toBeInTheDocument();
    expect(screen.getByText("No review needed")).toBeInTheDocument();
    expect(screen.getByText("Similarity")).toBeInTheDocument();
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
        frameworkId="fw_123"
        frameworkStatus="pipeline_failed"
      />,
    );

    expect(screen.getByText("Review required")).toBeInTheDocument();
    expect(
      screen.getByText(/replace or resolve the flagged artifact/i),
    ).toBeInTheDocument();
  });

  it("surfaces a near-duplicate as an admin-reviewed hard block", () => {
    render(
      <PipelineStatusPanel
        artifacts={[
          {
            ...baseArtifact,
            near_duplicate_blocked: true,
          },
        ]}
        frameworkId="fw_123"
        frameworkStatus="pipeline_failed"
      />,
    );

    expect(screen.getByText("Near duplicate")).toBeInTheDocument();
    expect(screen.getByText(/admin review is required/i)).toBeInTheDocument();
  });

  it("shows non-blocking similarity notices with review context", () => {
    render(
      <PipelineStatusPanel
        artifacts={[
          {
            ...baseArtifact,
            similarity_notice: {
              average_review_score: "4.50",
              jaccard: "0.8000",
              nearest_match_artifact_id: "art_999",
              nearest_match_framework_id: "fw_999",
              nearest_match_title: "Published Risk Framework",
              review_count: 2,
            },
          },
        ]}
        frameworkId="fw_123"
        frameworkStatus="pipeline_passed"
      />,
    );

    expect(screen.getByText("Notice")).toBeInTheDocument();
    expect(screen.getByText(/published risk framework/i)).toBeInTheDocument();
    expect(screen.getByText(/4.50 average from 2 reviews/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Acknowledge notice" }),
    ).toBeInTheDocument();
  });
});
