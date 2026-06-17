"use client";

/**
 * Contributor artifact uploader.
 *
 * Uses backend-issued S3 presigned POST targets and then confirms the artifact
 * through the generated API so the processing pipeline can start.
 */
import { useState } from "react";

import {
  confirmArtifactUpload,
  requestArtifactUploadUrl,
} from "@/lib/generated/sdk.gen";
import type { ArtifactResponse } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/** Total artifact byte cap per Framework, mirroring the backend limit. */
const ARTIFACT_MAX_TOTAL_BYTES = 500 * 1024 * 1024;

/**
 * Accepted artifact MIME types, mirroring the backend allowlist
 * (`ALLOWED_ARTIFACT_MIME_TYPES`). The backend 415 check stays authoritative;
 * this drives the picker filter and a client pre-check for fast feedback.
 */
const ARTIFACT_ALLOWED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/zip",
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

/** Comma-joined `accept` attribute value for the file picker. */
const ARTIFACT_ACCEPT_ATTRIBUTE = ARTIFACT_ALLOWED_MIME_TYPES.join(",");

type ArtifactUploaderProps = {
  artifactCount: number;
  existingBytes: number;
  frameworkId: string;
  onUploaded: (artifact: ArtifactResponse) => void;
};

/**
 * Render drag/drop-style artifact upload control.
 *
 * @param props - Framework id, current artifact count, and success callback.
 */
export function ArtifactUploader({
  artifactCount,
  existingBytes,
  frameworkId,
  onUploaded,
}: ArtifactUploaderProps) {
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function handleFile(file: File | null) {
    if (!file) {
      return;
    }

    // Mirror the backend 415 gate client-side so an unsupported file never makes
    // the round-trip. The picker `accept` filter is advisory only (drag-drop and
    // "all files" bypass it), so re-check here. Backend stays authoritative.
    if (
      !(ARTIFACT_ALLOWED_MIME_TYPES as readonly string[]).includes(file.type)
    ) {
      setMessage(
        "That file type is not supported. Upload PDF, Word, Excel, PowerPoint, ZIP, or an image (JPEG, PNG, WebP).",
      );
      return;
    }

    // Mirror the backend 413 gate client-side so an over-limit file never makes
    // the round-trip or starts an S3 upload. Backend stays authoritative.
    if (existingBytes + file.size > ARTIFACT_MAX_TOTAL_BYTES) {
      setMessage("Framework artifacts exceed the 500MB limit.");
      return;
    }

    configureBrowserClient();
    setMessage(null);
    setUploading(true);

    const requestResult = await requestArtifactUploadUrl({
      body: {
        file_size: file.size,
        filename: file.name,
        mime_type: file.type as never,
      },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });

    if (!requestResult.response.ok || !requestResult.data) {
      setMessage(describeGeneratedError(requestResult.error));
      setUploading(false);
      return;
    }

    const formData = new FormData();
    for (const [key, value] of Object.entries(requestResult.data.fields)) {
      formData.append(key, String(value));
    }
    formData.append("file", file);

    const uploadResponse = await fetch(requestResult.data.upload_url, {
      body: formData,
      method: "POST",
    });

    if (!uploadResponse.ok) {
      setMessage("Artifact upload failed before confirmation.");
      setUploading(false);
      return;
    }

    const confirmResult = await confirmArtifactUpload({
      body: { artifact_id: requestResult.data.artifact_id },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });

    setUploading(false);
    if (!confirmResult.response.ok || !confirmResult.data) {
      setMessage(describeGeneratedError(confirmResult.error));
      return;
    }

    setMessage("Artifact uploaded. Processing has started.");
    onUploaded(confirmResult.data);
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <h2 className="font-heading text-lg font-bold text-foreground">
        Artifacts
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Upload PDF, Word, Excel, PowerPoint, ZIP, or image packages for private
        processing. Up to 500 MB total across all artifacts.
      </p>
      <label className="mt-4 flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-background px-4 text-center text-sm text-foreground-muted">
        <span className="font-semibold text-foreground">
          {uploading
            ? "Uploading"
            : artifactCount > 0
              ? "Add another artifact"
              : "Choose artifact"}
        </span>
        <span>
          {artifactCount > 0
            ? "Adds a new artifact — does not replace existing files. Pipeline starts after the upload is confirmed."
            : "Pipeline starts after the upload is confirmed."}
        </span>
        <input
          accept={ARTIFACT_ACCEPT_ATTRIBUTE}
          className="sr-only"
          disabled={uploading}
          onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
          type="file"
        />
      </label>
      {message ? <p className="mt-3 text-sm text-foreground-muted">{message}</p> : null}
    </section>
  );
}
