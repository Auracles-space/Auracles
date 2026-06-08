"use client";

/**
 * Contributor artifact uploader.
 *
 * Uses backend-issued S3 presigned POST targets and then confirms the artifact
 * through the generated API so the processing pipeline can start.
 */
import { usePathname } from "next/navigation";
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
import { resolveMarketplaceActionRedirect } from "@/lib/marketplace/action-redirect";

type ArtifactUploaderProps = {
  frameworkId: string;
  onUploaded: (artifact: ArtifactResponse) => void;
};

/**
 * Render drag/drop-style artifact upload control.
 *
 * @param props - Framework id and success callback.
 */
export function ArtifactUploader({
  frameworkId,
  onUploaded,
}: ArtifactUploaderProps) {
  const pathname = usePathname();
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function handleFile(file: File | null) {
    if (!file) {
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

    const redirect = resolveMarketplaceActionRedirect({
      error: requestResult.error,
      pathname,
    });
    if (redirect) {
      window.location.assign(redirect);
      return;
    }

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
    <section className="rounded-[8px] border border-border-default bg-surface-2 p-5">
      <h2 className="font-heading text-lg font-bold text-foreground">
        Artifacts
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Upload PDF, Office, or ZIP framework packages for private processing.
      </p>
      <label className="mt-4 flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-[8px] border border-dashed border-border-strong bg-background px-4 text-center text-sm text-foreground-muted">
        <span className="font-semibold text-foreground">
          {uploading ? "Uploading" : "Choose artifact"}
        </span>
        <span>Pipeline starts after the upload is confirmed.</span>
        <input
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
