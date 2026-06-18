"use client";

/**
 * Contributor artifact manifest.
 *
 * Lists attached artifacts with their processing/scan state and the draft-only
 * controls to remove an artifact or designate one as the public preview.
 * Preview selection mirrors the backend `set_preview_artifact` rule: only a
 * draft Framework may change its preview, so the controls are draft-gated and
 * the backend stays authoritative.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch } from "@/lib/generated/sdk.gen";
import type {
  ArtifactResponse,
  FrameworkResponse,
} from "@/lib/generated/types.gen";
import { formatFileSize } from "@/lib/marketplace/format";

type ArtifactManifestProps = {
  artifacts: ArtifactResponse[];
  canRemove: boolean;
  frameworkId: string;
  frameworkStatus: string;
  previewArtifactId: string | null;
  onPreviewSet: (framework: FrameworkResponse) => void;
  onRemove: (artifactId: string) => void;
};

/** Processing state where the pipeline is actively running on the artifact. */
const IN_FLIGHT_PROCESSING = new Set(["processing"]);

/**
 * Decide whether an artifact is safe to expose as the public preview.
 *
 * The preview is publicly downloadable, so it must have cleared processing and
 * carry no unresolved PII. A file whose PII was redacted and accepted is
 * allowed; an unresolved PII flag is not.
 *
 * @param artifact - Artifact to evaluate.
 * @returns True when the artifact may be designated as preview.
 */
function canBePreview(artifact: ArtifactResponse): boolean {
  return (
    artifact.processing_status === "processed" &&
    !artifact.pii_review_needed &&
    (!artifact.pii_detected || artifact.redaction_accepted)
  );
}

/**
 * Render attached artifact status rows with removal and preview controls.
 *
 * @param props - Artifact list, framework context, and draft-only callbacks.
 */
export function ArtifactManifest({
  artifacts,
  canRemove,
  frameworkId,
  frameworkStatus,
  previewArtifactId,
  onPreviewSet,
  onRemove,
}: ArtifactManifestProps) {
  // Preview selection is only legal while the Framework is a draft, matching the
  // backend `_require_draft` gate. Published frameworks must start a new draft
  // version to change their preview.
  const canSetPreview = frameworkStatus === "draft";
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSetPreview(artifactId: string) {
    configureBrowserClient();
    setPendingId(artifactId);
    setError(null);
    const result =
      await setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch({
        body: { artifact_id: artifactId },
        headers: getAccessTokenHeaders(),
        path: { framework_id: frameworkId },
      });
    setPendingId(null);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    onPreviewSet(result.data);
  }

  return (
    <section className="min-w-0 rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-heading text-lg font-bold text-foreground">
          Artifact manifest
        </h2>
        <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {artifacts.length} file{artifacts.length === 1 ? "" : "s"}
        </span>
      </div>
      {canSetPreview ? (
        <p className="mt-1 text-xs text-foreground-muted">
          Choose one processed file as the public preview. Shoppers can open it
          before purchasing.
        </p>
      ) : null}
      {artifacts.length === 0 ? (
        <p className="mt-3 text-sm text-foreground-muted">
          No artifacts yet. Upload at least one file above.
        </p>
      ) : (
        <div className="mt-3 divide-y divide-border-default">
          {artifacts.map((artifact) => {
            const isPreview = artifact.id === previewArtifactId;
            const showSetPreview =
              canSetPreview && !isPreview && canBePreview(artifact);
            return (
              <div
                className="flex flex-col gap-2 py-3 text-sm sm:flex-row sm:items-start sm:justify-between"
                key={artifact.id}
              >
                <div className="min-w-0">
                  <p className="truncate font-semibold text-foreground">
                    {artifact.name}
                  </p>
                  <p className="text-foreground-muted">
                    {formatFileSize(artifact.file_size)} · {artifact.scan_status}{" "}
                    · {artifact.processing_status}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {isPreview ? (
                    <span className="inline-flex min-h-8 items-center rounded-lg border border-accent/30 bg-accent/10 px-3 py-1 text-xs font-semibold text-accent">
                      Preview
                    </span>
                  ) : showSetPreview ? (
                    <button
                      className="min-h-11 rounded-lg border border-border-default px-3 py-1.5 text-xs font-semibold text-foreground-muted transition-colors hover:border-accent/40 hover:bg-accent/10 hover:text-accent disabled:opacity-60"
                      disabled={pendingId === artifact.id}
                      onClick={() => handleSetPreview(artifact.id)}
                      type="button"
                    >
                      {pendingId === artifact.id
                        ? "Setting…"
                        : "Set as preview"}
                    </button>
                  ) : null}
                  {canRemove &&
                  !IN_FLIGHT_PROCESSING.has(artifact.processing_status) ? (
                    <button
                      aria-label={`Remove ${artifact.name}`}
                      className="min-h-11 rounded-lg border border-border-default px-3 py-1.5 text-xs font-semibold text-foreground-muted transition-colors hover:border-error/40 hover:bg-error/10 hover:text-error"
                      onClick={() => onRemove(artifact.id)}
                      type="button"
                    >
                      Remove
                    </button>
                  ) : canRemove ? (
                    <span className="text-xs font-medium text-foreground-muted">
                      Processing…
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
    </section>
  );
}
