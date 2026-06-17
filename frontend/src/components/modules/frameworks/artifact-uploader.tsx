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
  const [isDragging, setIsDragging] = useState(false);

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
    <section className="min-w-0 rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <h2 className="font-heading text-lg font-bold text-foreground">
        Artifacts
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Upload PDF, Word, Excel, PowerPoint, ZIP, or image packages for private
        processing. Up to 500 MB total across all artifacts.
      </p>
      <label
        className={[
          "mt-4 flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-8 text-center text-sm transition-all duration-200 outline-none",
          isDragging
            ? "border-accent bg-accent/5 scale-[1.01]"
            : "border-border-strong bg-background hover:border-accent hover:bg-surface-3",
          uploading ? "opacity-60 cursor-not-allowed" : ""
        ].join(" ")}
        onDragOver={(e) => {
          if (!uploading) {
            e.preventDefault();
            setIsDragging(true);
          }
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          if (!uploading) {
            e.preventDefault();
            setIsDragging(false);
            handleFile(e.dataTransfer.files?.[0] ?? null);
          }
        }}
      >
        <div className="flex flex-col items-center gap-3">
          <div className={[
            "flex h-12 w-12 items-center justify-center rounded-xl bg-surface-2 text-foreground-muted border border-border-default transition-colors",
            isDragging ? "text-accent bg-accent/10 border-accent/20" : "group-hover:text-foreground"
          ].join(" ")}>
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </div>

          <div className="space-y-1">
            <span className="font-semibold text-foreground block">
              {uploading
                ? "Uploading..."
                : isDragging
                  ? "Drop files here"
                  : artifactCount > 0
                    ? "Add another artifact"
                    : "Upload files"}
            </span>
            <span className="text-xs text-foreground-muted block max-w-md">
              {isDragging
                ? "Release to drop the file"
                : artifactCount > 0
                  ? "Adds a new artifact — does not replace existing files. Pipeline starts after confirmation."
                  : "Drag and drop your file here, or click to browse."}
            </span>
          </div>
        </div>
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
