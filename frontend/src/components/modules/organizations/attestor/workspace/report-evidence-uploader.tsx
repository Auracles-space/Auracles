/**
 * Evidence attachment control for the attestor's final report.
 *
 * Files go straight from the browser to private storage, so the API only
 * learns an upload happened when this component confirms it — and that
 * confirmation is what starts the virus scan. Each file is uploaded once and
 * then watched until the scan returns a verdict; the report may only reference
 * files that came back clean.
 *
 * Maps to: FR-ATT-014.
 */

"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

import {
  confirmAttestationEvidenceUpload,
  createAttestationEvidenceUpload,
  getAttestationEvidenceUpload,
} from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";

/** Where one attached file has got to. */
type EvidenceState = "uploading" | "scanning" | "ready" | "failed";

/** One file the reviewer attached to the report. */
interface EvidenceUpload {
  /** Stable row id, also the upload session id once one exists. */
  id: string;
  name: string;
  sizeBytes: number;
  state: EvidenceState;
  /** Storage key, known once the upload session is created. */
  fileKey?: string;
  /** Why the file cannot be attached, shown when the state is failed. */
  problem?: string;
}

/** What the report panel needs to know about the attached evidence. */
export interface EvidenceSelection {
  /** Storage keys of files that scanned clean. */
  fileKeys: string[];
  /** False while any file is still uploading, scanning, or failed. */
  settled: boolean;
}

export interface ReportEvidenceUploaderProps {
  attestationId: string;
  /** Called whenever the attached set changes. */
  onChange: (selection: EvidenceSelection) => void;
  /** Locks the file input while the report is being submitted. */
  disabled?: boolean;
  /** Gap between scan checks; shortened in tests. */
  pollIntervalMs?: number;
}

// A clean bill of health normally lands in seconds. Waiting past this points at
// a stuck worker rather than a slow scan, and the reviewer is better served by
// being told than by an indefinite spinner.
const SCAN_TIMEOUT_MS = 3 * 60 * 1000;
const DEFAULT_POLL_INTERVAL_MS = 3000;

/** Describe one file's state in the reviewer's words. */
function describeState(upload: EvidenceUpload): string {
  if (upload.state === "uploading") return "Uploading…";
  if (upload.state === "scanning") return "Checking this file for viruses…";
  if (upload.state === "ready") return "Checked and ready";
  return upload.problem ?? "This file could not be attached.";
}

/** Wait, resolving after the given delay. */
function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function ReportEvidenceUploader({
  attestationId,
  onChange,
  disabled = false,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: ReportEvidenceUploaderProps) {
  const [uploads, setUploads] = useState<EvidenceUpload[]>([]);

  // Report the selection upward on every change. The parent gates its submit
  // button on `settled`, so a file mid-scan holds the report back.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  useEffect(() => {
    onChangeRef.current({
      fileKeys: uploads
        .filter((upload) => upload.state === "ready" && upload.fileKey)
        .map((upload) => upload.fileKey as string),
      settled: uploads.every((upload) => upload.state === "ready"),
    });
  }, [uploads]);

  // Unmounting mid-scan must not leave a polling loop running.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const patch = useCallback((id: string, changes: Partial<EvidenceUpload>) => {
    if (!mounted.current) return;
    setUploads((current) =>
      current.map((upload) =>
        upload.id === id ? { ...upload, ...changes } : upload,
      ),
    );
  }, []);

  /**
   * Upload one file, confirm it, and watch the scan through to a verdict.
   *
   * @param rowId - Row to update as the file progresses.
   * @param file - The file the reviewer chose.
   */
  const attach = useCallback(
    async (rowId: string, file: File) => {
      const created = await createAttestationEvidenceUpload({
        path: { attestation_id: attestationId },
        body: {
          file_name: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
        },
        headers: getAccessTokenHeaders(),
      });
      if (created.error || !created.data) {
        throw new Error("This file could not be uploaded. Try again.");
      }
      const { id: sessionId, url, fields, s3_key: fileKey } = created.data;
      patch(rowId, { id: sessionId, fileKey });

      const form = new FormData();
      Object.entries(fields ?? {}).forEach(([key, value]) => {
        form.append(key, value as string);
      });
      form.append("file", file);
      const stored = await fetch(url, { method: "POST", body: form });
      if (!stored.ok) {
        throw new Error("This file could not be uploaded. Try again.");
      }

      // Storage took the file; this is what starts the virus scan.
      const confirmed = await confirmAttestationEvidenceUpload({
        path: { attestation_id: attestationId, upload_session_id: sessionId },
        headers: getAccessTokenHeaders(),
      });
      if (confirmed.error) {
        throw new Error("This file could not be checked. Remove it and retry.");
      }
      patch(sessionId, { state: "scanning" });

      const giveUpAt = Date.now() + SCAN_TIMEOUT_MS;
      let scanStatus = confirmed.data?.scan_status ?? "pending_scan";
      while (scanStatus === "pending_scan") {
        if (Date.now() > giveUpAt) {
          throw new Error(
            "This file is taking too long to check. Remove it and try again.",
          );
        }
        await wait(pollIntervalMs);
        if (!mounted.current) return;
        const polled = await getAttestationEvidenceUpload({
          path: { attestation_id: attestationId, upload_session_id: sessionId },
          headers: getAccessTokenHeaders(),
        });
        if (polled.error || !polled.data) {
          throw new Error("This file could not be checked. Remove it and retry.");
        }
        scanStatus = polled.data.scan_status;
      }

      if (scanStatus !== "clean") {
        throw new Error("This file did not pass the virus check.");
      }
      patch(sessionId, { state: "ready" });
    },
    [attestationId, patch, pollIntervalMs],
  );

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(event.target.files ?? []);
    if (chosen.length === 0) return;
    // Clearing the input lets the same file be re-picked after a removal.
    event.target.value = "";

    chosen.forEach((file) => {
      const rowId = `pending-${crypto.randomUUID()}`;
      setUploads((current) => [
        ...current,
        {
          id: rowId,
          name: file.name,
          sizeBytes: file.size,
          state: "uploading",
        },
      ]);
      void attach(rowId, file).catch((error: unknown) => {
        // The row may already carry its session id by the time this throws, so
        // mark both candidates; only the surviving row matches.
        const problem =
          error instanceof Error
            ? error.message
            : "This file could not be attached.";
        setUploads((current) =>
          current.map((upload) =>
            upload.id === rowId || upload.name === file.name
              ? { ...upload, state: "failed", problem }
              : upload,
          ),
        );
      });
    });
  };

  const remove = (id: string) => {
    setUploads((current) => current.filter((upload) => upload.id !== id));
  };

  return (
    <div>
      <label
        className="block text-sm font-medium text-foreground mb-1"
        htmlFor="report-evidence-files"
      >
        Evidence files (optional)
      </label>
      <p className="text-xs text-foreground-muted mb-2">
        Attach supporting documents (PDFs, spreadsheets). Each file is checked
        for viruses before it can go with the report.
      </p>
      <input
        id="report-evidence-files"
        type="file"
        multiple
        disabled={disabled}
        onChange={handleFileChange}
        className="block w-full text-sm text-foreground-muted file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-foreground file:text-background hover:file:bg-foreground/90 transition-colors"
      />
      {uploads.length > 0 && (
        <ul className="mt-3 space-y-2">
          {uploads.map((upload) => (
            <li
              key={upload.id}
              className="flex flex-col gap-2 rounded-xl border border-border-default bg-surface-2 p-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-foreground">{upload.name}</p>
                <p
                  className={`text-xs ${
                    upload.state === "failed"
                      ? "text-error"
                      : upload.state === "ready"
                        ? "text-success"
                        : "text-foreground-muted"
                  }`}
                >
                  {describeState(upload)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => remove(upload.id)}
                className="min-h-12 shrink-0 rounded-xl border border-border-default px-4 text-sm text-foreground hover:bg-surface-1 sm:min-h-0 sm:py-2"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
