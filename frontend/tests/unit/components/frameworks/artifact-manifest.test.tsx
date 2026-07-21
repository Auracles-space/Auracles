import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactManifest } from "@/components/modules/frameworks/artifact-manifest";
import { FrameworkApiError } from "@/lib/frameworks/framework-api";
import type { ArtifactResponse } from "@/lib/generated/types.gen";

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
  it("sets a processed non-PII artifact as preview on a draft framework", async () => {
    const setPreviewArtifact = vi.fn().mockResolvedValue({
      id: "framework-1",
      preview_artifact_id: "artifact-1",
    });
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
        setPreviewArtifact={setPreviewArtifact}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /set .*as preview/i }),
    );

    await waitFor(() => {
      expect(setPreviewArtifact).toHaveBeenCalledWith("artifact-1");
    });
    expect(onPreviewSet).toHaveBeenCalled();
  });

  it("surfaces a safe error when the preview request fails", async () => {
    const setPreviewArtifact = vi
      .fn()
      .mockRejectedValue(new Error("Request failed"));

    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
        setPreviewArtifact={setPreviewArtifact}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /set .*as preview/i }),
    );

    await waitFor(() => {
      expect(screen.getByText("Request failed")).toBeInTheDocument();
    });
  });

  it("still offers preview selection on a pipeline_failed framework", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="pipeline_failed"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /set .*as preview/i }),
    ).toBeInTheDocument();
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
        setPreviewArtifact={vi.fn()}
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
        setPreviewArtifact={vi.fn()}
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
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /set .*as preview/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/^preview$/i)).not.toBeInTheDocument();
  });
});

describe("ArtifactManifest connector re-sync", () => {
  /** A Drive-bound artifact fixture that is eligible to re-sync. */
  function driveArtifact(
    overrides: Partial<ArtifactResponse> = {},
  ): ArtifactResponse {
    return artifact({
      id: "drive-1",
      name: "brief.docx",
      source_kind: "google_drive",
      ...overrides,
    });
  }

  it("re-syncs a Drive-bound artifact and refreshes on success", async () => {
    const resyncArtifact = vi.fn().mockResolvedValue(driveArtifact());
    const onResynced = vi.fn();

    render(
      <ArtifactManifest
        artifacts={[driveArtifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        onResynced={onResynced}
        previewArtifactId={null}
        resyncArtifact={resyncArtifact}
        setPreviewArtifact={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /re-sync/i }));

    await waitFor(() => {
      expect(resyncArtifact).toHaveBeenCalledWith("drive-1");
    });
    expect(onResynced).toHaveBeenCalledOnce();
  });

  it("shows an informational note (not an error) when the source is unchanged", async () => {
    const resyncArtifact = vi
      .fn()
      .mockRejectedValue(
        new FrameworkApiError("The source has not changed.", "already_up_to_date"),
      );
    const onResynced = vi.fn();

    render(
      <ArtifactManifest
        artifacts={[driveArtifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        onResynced={onResynced}
        previewArtifactId={null}
        resyncArtifact={resyncArtifact}
        setPreviewArtifact={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /re-sync/i }));

    await waitFor(() => {
      expect(screen.getByText(/already up to date/i)).toBeInTheDocument();
    });
    // An unchanged source is not a failure, so nothing reloads.
    expect(onResynced).not.toHaveBeenCalled();
  });

  it("does not offer re-sync for an uploaded (non-connector) artifact", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact({ source_kind: "upload" })]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        onResynced={vi.fn()}
        previewArtifactId={null}
        resyncArtifact={vi.fn()}
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /re-sync/i }),
    ).not.toBeInTheDocument();
  });

  it("hides re-sync when no re-sync handler is wired (e.g. org frameworks)", () => {
    render(
      <ArtifactManifest
        artifacts={[driveArtifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="draft"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /re-sync/i }),
    ).not.toBeInTheDocument();
  });

  it("hides re-sync once the framework is published (no longer editable)", () => {
    render(
      <ArtifactManifest
        artifacts={[driveArtifact()]}
        canRemove={false}
        frameworkId="framework-1"
        frameworkStatus="published"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        onResynced={vi.fn()}
        previewArtifactId={null}
        resyncArtifact={vi.fn()}
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /re-sync/i }),
    ).not.toBeInTheDocument();
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
        setPreviewArtifact={vi.fn()}
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
        setPreviewArtifact={vi.fn()}
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
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.queryByText(/buyers won't see a sample/i),
    ).not.toBeInTheDocument();
  });

  it("nudges to set a preview at pipeline_passed before publish", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove
        frameworkId="framework-1"
        frameworkStatus="pipeline_passed"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/buyers won't see a sample/i),
    ).toBeInTheDocument();
  });

  it("stays quiet once the framework is published", () => {
    render(
      <ArtifactManifest
        artifacts={[artifact()]}
        canRemove={false}
        frameworkId="framework-1"
        frameworkStatus="published"
        onPreviewSet={vi.fn()}
        onRemove={vi.fn()}
        previewArtifactId={null}
        setPreviewArtifact={vi.fn()}
      />,
    );

    expect(
      screen.queryByText(/buyers won't see a sample/i),
    ).not.toBeInTheDocument();
  });
});
