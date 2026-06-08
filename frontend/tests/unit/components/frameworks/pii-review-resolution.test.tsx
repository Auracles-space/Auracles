import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PiiReviewResolution } from "@/components/modules/frameworks/pii-review-resolution";
import {
  acceptArtifactRedaction,
  resolveArtifactPiiReview,
} from "@/lib/generated/sdk.gen";
import type { ArtifactResponse } from "@/lib/generated/types.gen";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptArtifactRedaction: vi.fn(),
  client: { setConfig: vi.fn() },
  resolveArtifactPiiReview: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ accessToken: "access-token" }),
  },
}));

const baseArtifact: ArtifactResponse = {
  created_at: "2026-06-08T10:00:00Z",
  file_key: "private/frameworks/artifact.pdf",
  file_size: 1024,
  framework_id: "fw_123",
  id: "art_123",
  mime_type: "application/pdf",
  name: "Operating Model.pdf",
  pii_detected: true,
  pii_review_needed: true,
  processing_status: "flagged_pii",
  rarity_score: null,
  redaction_accepted: false,
  redaction_available: true,
  redaction_status: "generated",
  scan_status: "clean",
};

describe("PiiReviewResolution", () => {
  beforeEach(() => {
    refresh.mockReset();
    vi.mocked(acceptArtifactRedaction).mockReset();
    vi.mocked(resolveArtifactPiiReview).mockReset();
  });

  it("accepts a generated redacted copy without exposing storage details", async () => {
    vi.mocked(acceptArtifactRedaction).mockResolvedValue({
      data: { ...baseArtifact, pii_review_needed: false },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(
      <PiiReviewResolution artifacts={[baseArtifact]} frameworkId="fw_123" />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /accept redacted copy/i }),
    );

    await waitFor(() => {
      expect(acceptArtifactRedaction).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { artifact_id: "art_123", framework_id: "fw_123" },
        }),
      );
    });
    expect(resolveArtifactPiiReview).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByText(/redacted\/a\.pdf/i)).not.toBeInTheDocument();
  });

  it("keeps replacement rerun available when no redacted copy exists", () => {
    render(
      <PiiReviewResolution
        artifacts={[
          {
            ...baseArtifact,
            redaction_available: false,
            redaction_status: null,
          },
        ]}
        frameworkId="fw_123"
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
