"use client";

/**
 * Contributor artifact uploader.
 *
 * Uses backend-issued S3 presigned POST targets and then confirms the artifact
 * through the generated API so the processing pipeline can start.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { GoogleDrivePicker } from "@/components/modules/artifacts/google-drive-picker";
import type { ArtifactResponse } from "@/lib/generated/types.gen";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";

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
  api: FrameworkApi;
  artifactCount: number;
  allowConnectorImport?: boolean;
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
  api,
  artifactCount,
  allowConnectorImport = true,
  existingBytes,
  frameworkId,
  onUploaded,
}: ArtifactUploaderProps) {
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [showDrivePicker, setShowDrivePicker] = useState(false);

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

    setMessage(null);
    setUploading(true);

    let uploadTarget;
    try {
      uploadTarget = await api.createArtifactUpload(frameworkId, {
        file_size: file.size,
        filename: file.name,
        mime_type: file.type as never,
      });
    } catch (caught) {
      setMessage(
        caught instanceof Error ? caught.message : "The request could not be completed.",
      );
      setUploading(false);
      return;
    }

    const formData = new FormData();
    for (const [key, value] of Object.entries(uploadTarget.fields)) {
      formData.append(key, String(value));
    }
    formData.append("file", file);

    // The browser PUT/POST goes straight to S3, not our API. If the bucket is
    // missing a CORS rule for this origin the browser blocks the response and
    // `fetch` rejects — so this must be guarded, or the control hangs on
    // "Uploading..." forever with the real failure swallowed.
    let uploadResponse: Response;
    try {
      uploadResponse = await fetch(uploadTarget.upload_url, {
        body: formData,
        method: "POST",
      });
    } catch {
      setMessage(
        "Artifact upload failed — couldn't reach storage. Try again in a moment.",
      );
      setUploading(false);
      return;
    }

    if (!uploadResponse.ok) {
      setMessage("Artifact upload failed before confirmation.");
      setUploading(false);
      return;
    }

    let artifact: ArtifactResponse;
    try {
      artifact = await api.confirmArtifact(
        frameworkId,
        uploadTarget.artifact_id,
        { artifact_id: uploadTarget.artifact_id },
      );
    } catch (caught) {
      setMessage(
        caught instanceof Error
          ? caught.message
          : "Artifact upload failed before confirmation.",
      );
      setUploading(false);
      return;
    }

    setUploading(false);
    setMessage("Artifact uploaded. Processing has started.");
    onUploaded(artifact);
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
      {allowConnectorImport && !showDrivePicker && (
        <>
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-border-default" />
            </div>
            <div className="relative flex justify-center text-xs uppercase font-semibold tracking-wider">
              <span className="bg-surface-2 px-3 text-foreground-muted">Or</span>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowDrivePicker(true)}
            className="flex min-h-12 w-full items-center justify-center gap-3 rounded-xl border border-border-strong bg-background px-4 text-sm font-semibold text-foreground shadow-sm outline-none transition-all hover:bg-surface-3 hover:border-accent/40 focus-visible:ring-2 focus-visible:ring-accent"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 87.3 78" className="h-5 w-5 shrink-0">
              <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
              <path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z" fill="#00ac47"/>
              <path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z" fill="#ea4335"/>
              <path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
              <path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/>
              <path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>
            </svg>
            Import from Google Drive
          </button>
        </>
      )}

      {allowConnectorImport && showDrivePicker && (
        <div className="mt-5 animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="mb-3 flex items-center justify-between rounded-xl bg-surface-3 p-3 pl-4 border border-border-default">
            <span className="text-sm font-semibold text-foreground">Importing from Google Drive</span>
            <Button variant="secondary" onClick={() => setShowDrivePicker(false)} className="min-h-8 h-8 px-3 text-xs">
              Cancel
            </Button>
          </div>
          <div className="rounded-xl border border-border-default bg-background p-1 shadow-sm">
            <GoogleDrivePicker
              frameworkId={frameworkId}
              onArtifactCreated={(artifact) => {
                setShowDrivePicker(false);
                setMessage("Artifact imported from Google Drive. Processing has started.");
                onUploaded(artifact);
              }}
            />
          </div>
        </div>
      )}
      {message ? <p className="mt-3 text-sm text-foreground-muted">{message}</p> : null}
    </section>
  );
}
