"use client";

/**
 * Draft source-preview badge.
 *
 * Fetches the owner-only source preview for a draft connector-bound artifact
 * and renders the current thumbnail plus a drift badge when the source changed
 * since the last byte sync.
 *
 * Maps to: docs/superpowers/plans/2026-07-08-connectors-phase-b.md Task 5.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet,
} from "@/lib/generated/sdk.gen";

type SourcePreviewBadgeProps = {
  artifactId: string;
  frameworkId: string;
};

type SourcePreviewState = {
  previewUrl: string;
  sourceUpdated: boolean;
};

/**
 * Render the live source thumbnail for a draft Google Drive artifact.
 *
 * @param props - Framework and artifact ids used to fetch the owner-only preview.
 */
export function SourcePreviewBadge({
  artifactId,
  frameworkId,
}: SourcePreviewBadgeProps) {
  const [preview, setPreview] = useState<SourcePreviewState | null>(null);

  useEffect(() => {
    let isActive = true;

    async function loadPreview() {
      configureBrowserClient();
      // The badge is optional chrome on a page that works without it, so a
      // failed request leaves it unrendered rather than surfacing an error the
      // owner cannot act on. Caught rather than left to reject: an uncaught
      // rejection here escapes the component as a page-level error.
      let result;
      try {
        result =
          await getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet(
            {
              headers: getAccessTokenHeaders(),
              path: { artifact_id: artifactId, framework_id: frameworkId },
            },
          );
      } catch {
        return;
      }
      if (!isActive || !result.response.ok || !result.data?.preview_url) {
        return;
      }
      setPreview({
        previewUrl: result.data.preview_url,
        sourceUpdated: result.data.source_updated,
      });
    }

    void loadPreview();
    return () => {
      isActive = false;
    };
  }, [artifactId, frameworkId]);

  if (!preview) {
    return null;
  }

  const previewImage = (
    // eslint-disable-next-line @next/next/no-img-element -- Short-lived presigned URLs do not fit static Next image allowlists.
    <img
      alt="Live source preview"
      className="h-16 w-16 shrink-0 rounded-xl border border-border-default bg-surface-1 object-cover shadow-sm"
      loading="lazy"
      src={preview.previewUrl}
    />
  );

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      {previewImage}
      {preview.sourceUpdated ? (
        <span className="inline-flex items-center rounded-full border border-accent/25 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent">
          Source updated
        </span>
      ) : null}
    </div>
  );
}
