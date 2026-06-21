"use client";

/**
 * Deliverable submission form for an assigned Contributor.
 *
 * Captures a title and a description of what was achieved, uploads one or more
 * evidence files to S3 via presigned POST (reusing the workspace upload
 * session), then submits the Deliverable with the resulting file keys. Files
 * are required — the backend rejects a Deliverable with no file.
 *
 * Maps to: FR-PROJ-008.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  createWorkspaceUploadSession,
  submitDeliverable,
} from "@/lib/generated/sdk.gen";
import type { DeliverableResponse } from "@/lib/generated/types.gen";

const MAX_FILE_BYTES = 25 * 1024 * 1024;

type DeliverableSubmitFormProps = {
  /** Project the Milestone belongs to. */
  projectId: string;
  /** Milestone the Deliverable is submitted against. */
  milestoneId: string;
  /** Called with the created Deliverable on success. */
  onSubmitted: (deliverable: DeliverableResponse) => void;
  /** Dismiss the form without submitting. */
  onCancel: () => void;
};

/**
 * Render the Deliverable submission form for one funded Milestone.
 */
export function DeliverableSubmitForm({
  projectId,
  milestoneId,
  onSubmitted,
  onCancel,
}: DeliverableSubmitFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    name.trim().length > 0 &&
    description.trim().length > 0 &&
    files.length > 0 &&
    !submitting;

  /** Upload one file via a presigned workspace session and return its S3 key. */
  async function uploadFile(file: File): Promise<string> {
    const session = await createWorkspaceUploadSession({
      headers: getAccessTokenHeaders(),
      path: { project_id: projectId },
      body: {
        file_name: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
      },
    });
    if (!session.response.ok || !session.data) {
      throw new Error(describeGeneratedError(session.error));
    }
    const formData = new FormData();
    for (const [key, value] of Object.entries(session.data.fields)) {
      formData.append(key, String(value));
    }
    formData.append("file", file);
    const upload = await fetch(session.data.url, {
      method: "POST",
      body: formData,
    });
    if (!upload.ok) {
      throw new Error(`Upload failed for ${file.name}.`);
    }
    return session.data.s3_key;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    try {
      const fileKeys: string[] = [];
      for (const file of files) {
        if (file.size > MAX_FILE_BYTES) {
          throw new Error(`${file.name} exceeds the 25MB limit.`);
        }
        fileKeys.push(await uploadFile(file));
      }
      const result = await submitDeliverable({
        headers: getAccessTokenHeaders(),
        path: { milestone_id: milestoneId, project_id: projectId },
        body: {
          name: name.trim(),
          description: description.trim(),
          file_keys: fileKeys,
        },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      onSubmitted(result.data);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Could not submit the deliverable.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className="mt-3 grid gap-3 rounded-xl border border-border-default bg-surface-1 p-4"
      onSubmit={handleSubmit}
    >
      <p className="text-sm font-semibold text-foreground">Submit deliverable</p>
      <label className="grid gap-1 text-sm">
        <span className="font-medium text-foreground">Title</span>
        <input
          className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Final procurement playbook"
          value={name}
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="font-medium text-foreground">What was achieved</span>
        <textarea
          className="min-h-24 rounded-xl border border-border-default bg-surface-1 px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Summarize the work completed for this milestone."
          value={description}
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="font-medium text-foreground">Files (required)</span>
        <input
          accept=".pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg,.webp,.txt,.md,.csv,.zip"
          className="text-sm text-foreground-muted file:mr-3 file:min-h-11 file:rounded-xl file:border-0 file:bg-surface-3 file:px-4 file:text-sm file:font-semibold file:text-foreground"
          multiple
          onChange={(event) =>
            setFiles(event.target.files ? Array.from(event.target.files) : [])
          }
          type="file"
        />
        <span className="text-xs text-foreground-subtle">
          PDF, Office docs, images, text, or ZIP — up to 25MB each.
        </span>
        {files.length > 0 ? (
          <span className="text-xs text-foreground-muted">
            {files.length} file{files.length === 1 ? "" : "s"} selected
          </span>
        ) : null}
      </label>
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <div className="flex flex-wrap gap-3">
        <button
          className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canSubmit}
          type="submit"
        >
          {submitting ? "Submitting" : "Submit deliverable"}
        </button>
        <button
          className="min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting}
          onClick={onCancel}
          type="button"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
