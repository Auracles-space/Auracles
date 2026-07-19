import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PiiReviewResolution } from "@/components/modules/frameworks/pii-review-resolution";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";
import type { ArtifactResponse } from "@/lib/generated/types.gen";

const baseArtifact: ArtifactResponse = {
  created_at: "2026-06-08T10:00:00Z",
  file_key: "private/frameworks/artifact.pdf",
  file_size: 1024,
  framework_id: "fw_123",
  id: "art_123",
  mime_type: "application/pdf",
  name: "Operating Model.pdf",
  source_kind: "upload",
  near_duplicate_blocked: false,
  pii_detected: true,
  pii_review_needed: true,
  processing_status: "flagged_pii",
  rarity_score: null,
  redaction_accepted: false,
  redaction_available: true,
  redaction_status: "generated",
  scan_status: "clean",
  similarity_notice: null,
} as ArtifactResponse;

/** Build a Framework API adapter double exposing only the PII actions used here. */
function makeApi(overrides: Partial<FrameworkApi> = {}): FrameworkApi {
  return {
    acceptRedaction: vi.fn().mockResolvedValue(baseArtifact),
    resolvePiiReview: vi.fn().mockResolvedValue(baseArtifact),
    ...overrides,
  } as unknown as FrameworkApi;
}

describe("PiiReviewResolution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <PiiReviewResolution
        api={makeApi()}
        artifacts={[baseArtifact]}
        frameworkId="fw_123"
        onClose={vi.fn()}
        onResolved={vi.fn()}
        open={false}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("accepts a generated redacted copy through the adapter, then reloads", async () => {
    const api = makeApi();
    const onResolved = vi.fn();

    render(
      <PiiReviewResolution
        api={api}
        artifacts={[baseArtifact]}
        frameworkId="fw_123"
        onClose={vi.fn()}
        onResolved={onResolved}
        open
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /accept redacted copy/i }),
    );

    await waitFor(() => {
      expect(api.acceptRedaction).toHaveBeenCalledWith("fw_123", "art_123");
    });
    expect(api.resolvePiiReview).not.toHaveBeenCalled();
    expect(onResolved).toHaveBeenCalled();
    expect(screen.queryByText(/redacted\/a\.pdf/i)).not.toBeInTheDocument();
  });

  it("re-runs PII review through the adapter, then reloads", async () => {
    const api = makeApi();
    const onResolved = vi.fn();

    render(
      <PiiReviewResolution
        api={api}
        artifacts={[
          { ...baseArtifact, redaction_available: false, redaction_status: null },
        ]}
        frameworkId="fw_123"
        onClose={vi.fn()}
        onResolved={onResolved}
        open
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /re-run pii review/i }));

    await waitFor(() => {
      expect(api.resolvePiiReview).toHaveBeenCalledWith("fw_123", "art_123");
    });
    expect(api.acceptRedaction).not.toHaveBeenCalled();
    expect(onResolved).toHaveBeenCalled();
  });

  it("names the detected PII categories so the contributor knows what to remove", () => {
    render(
      <PiiReviewResolution
        api={makeApi()}
        artifacts={[
          {
            ...baseArtifact,
            redaction_available: false,
            redaction_status: null,
            pii_types_found: ["EMAIL_ADDRESS", "PERSON", "PHONE_NUMBER"],
          },
        ]}
        frameworkId="fw_123"
        onClose={vi.fn()}
        onResolved={vi.fn()}
        open
      />,
    );

    expect(
      screen.getByText(/email addresses, names, and phone numbers/i),
    ).toBeInTheDocument();
  });

  it("explains when automatic redaction could not be generated", () => {
    render(
      <PiiReviewResolution
        api={makeApi()}
        artifacts={[
          {
            ...baseArtifact,
            redaction_available: false,
            redaction_status: "failed",
            pii_types_found: ["PERSON"],
          },
        ]}
        frameworkId="fw_123"
        onClose={vi.fn()}
        onResolved={vi.fn()}
        open
      />,
    );

    expect(
      screen.getByText(/couldn.t automatically redact/i),
    ).toBeInTheDocument();
  });

  it("keeps replacement rerun available when no redacted copy exists", () => {
    render(
      <PiiReviewResolution
        api={makeApi()}
        artifacts={[
          { ...baseArtifact, redaction_available: false, redaction_status: null },
        ]}
        frameworkId="fw_123"
        onClose={vi.fn()}
        onResolved={vi.fn()}
        open
      />,
    );

    expect(
      screen.queryByRole("button", { name: /accept redacted copy/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /re-run pii review/i }),
    ).toBeInTheDocument();
  });
});
