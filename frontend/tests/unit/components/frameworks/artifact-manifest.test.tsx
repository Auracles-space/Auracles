import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactManifest } from "@/components/modules/frameworks/artifact-manifest";
import type { ArtifactResponse } from "@/lib/generated/types.gen";
import { setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch: vi.fn(),
}));

const setPreview = vi.mocked(
  setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch,
);

/** Build an ArtifactResponse fixture with safe processed defaults. */
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
    rarity_score: "0.5",
    created_at: "2026-06-18T09:00:00Z",
    ...overrides,
  };
}

describe("ArtifactManifest preview controls", () => {
  beforeEach(() => {
    setPreview.mockReset();
  });

  it("sets a processed non-PII artifact as preview on a draft framework", async () => {
    setPreview.mockResolvedValue({
      data: { id: "framework-1", preview_artifact_id: "artifact-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    const onPreviewSet = vi.fn();

    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={onPreviewSet}
        onRemove={vi.fn()}
        previewArtifactId={null}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /set .*as preview/i }),
    );

    await waitFor(() => {
      expect(setPreview).toHaveBeenCalledWith({
        body: { artifact_id: "artifact-1" },
        headers: { Authorization: "Bearer access-token" },
        path: { framework_id: "framework-1" },
      });
    });
    expect(onPreviewSet).toHaveBeenCalled();
  });

  it("marks the current preview artifact and offers no set button for it", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId="artifact-1"
      />,
    );

    expect(screen.getByText(/^preview$/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /set .*as preview/i }),
    ).not.toBeInTheDocument();
  });

  it("does not offer preview for a PII-flagged or still-processing artifact", () => {
    render(
      <ArtifactManifest
        artifacts={[
          artifact({ id: "a-pii", pii_review_needed: true }),
          artifact({ id: "a-proc", processing_status: "processing" }),
        ]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /set .*as preview/i }),
    ).not.toBeInTheDocument();
  });

  it("hides preview controls entirely when the framework is not a draft", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove={false}
        frameworkId="framework-1"
        frameworkStatus="published"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /set .*as preview/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/^preview$/i)).not.toBeInTheDocument();
  });
});

describe("ArtifactManifest no-preview nudge", () => {
  it("nudges when a draft has an eligible file but no preview set", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
      />,
    );

    expect(
      screen.getByText(/buyers won't see a sample/i),
    ).toBeInTheDocument();
  });

  it("drops the nudge once a preview is set", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId="artifact-1"
      />,
    );

    expect(
      screen.queryByText(/buyers won't see a sample/i),
    ).not.toBeInTheDocument();
  });

  it("stays quiet when no file is eligible to be a preview yet", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact({ processing_status: "processing" })]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
      />,
    );

    expect(
      screen.queryByText(/buyers won't see a sample/i),
    ).not.toBeInTheDocument();
  });

  it("stays quiet when the framework is not a draft", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove={false}
        frameworkId="framework-1"
        frameworkStatus="pipeline_passed"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
      />,
    );

    expect(
      screen.queryByText(/buyers won't see a sample/i),
    ).not.toBeInTheDocument();
  });
});
