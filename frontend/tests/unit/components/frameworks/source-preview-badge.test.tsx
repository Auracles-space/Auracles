import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SourcePreviewBadge } from "@/components/modules/frameworks/source-preview-badge";
import { getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet:
    vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer access-token" })),
}));

const getPreview = vi.mocked(
  getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet,
);

describe("SourcePreviewBadge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the thumbnail and source-updated badge when the source drifted", async () => {
    getPreview.mockResolvedValue({
      data: {
        preview_url: "https://s3/thumb.png",
        source_last_synced_at: "2026-07-01T00:00:00Z",
        source_updated: true,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(
      <div style={{ width: "375px" }}>
        <SourcePreviewBadge artifactId="a1" frameworkId="fw1" />
      </div>,
    );

    expect(await screen.findByText(/source updated/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("img")).toHaveAttribute(
        "src",
        "https://s3/thumb.png",
      );
    });
    expect(screen.getByRole("img").parentElement).toHaveClass("flex-wrap");
  });

  it("shows no badge when the source is unchanged", async () => {
    getPreview.mockResolvedValue({
      data: {
        preview_url: "https://s3/thumb.png",
        source_last_synced_at: null,
        source_updated: false,
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    render(<SourcePreviewBadge artifactId="a1" frameworkId="fw1" />);

    await screen.findByRole("img");
    expect(screen.queryByText(/source updated/i)).toBeNull();
  });
});
