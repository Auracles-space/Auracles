"use client";

/**
 * Evidence files the attestor attached to a report.
 *
 * Shared by the requestor's attestation page and the admin attestation view,
 * so both can open what the report relied on. Links are short-lived presigned
 * URLs issued (and audited) by the API only for files that scanned clean; a
 * file still being scanned is listed without a link. Renders nothing when the
 * report has no evidence or the list cannot be loaded.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useEffect, useState } from "react";

import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { listAttestationEvidenceFiles } from "@/lib/generated/sdk.gen";
import type { AttestationEvidenceFile } from "@/lib/generated/types.gen";

/**
 * Render the report's evidence files with download links.
 *
 * @param attestationId - The attestation whose report evidence to list.
 */
export function ReportEvidenceFiles({ attestationId }: { attestationId: string }) {
  const [files, setFiles] = useState<AttestationEvidenceFile[]>([]);

  useEffect(() => {
    let active = true;
    async function load() {
      configureBrowserClient();
      const result = await listAttestationEvidenceFiles({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (active && result.response?.ok && result.data) {
        setFiles(result.data.files);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [attestationId]);

  if (files.length === 0) {
    return null;
  }

  return (
    <div className="mt-4">
      <p className="text-sm font-semibold text-foreground">Evidence files</p>
      <ul className="mt-2 grid gap-2">
        {files.map((file, index) => (
          <li
            className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-sm"
            key={`${file.file_name}-${index}`}
          >
            {file.download_url ? (
              <a
                className="min-h-11 break-all py-2 font-semibold text-accent underline-offset-4 hover:underline"
                href={file.download_url}
                rel="noopener noreferrer"
                target="_blank"
              >
                {file.file_name}
              </a>
            ) : (
              <>
                <span className="break-all text-foreground">{file.file_name}</span>
                <span className="text-xs text-foreground-muted">
                  {file.scan_status === "pending_scan"
                    ? "Still being scanned"
                    : "Unavailable"}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-foreground-muted">
        Links expire after 15 minutes. Opening files is recorded in the audit log.
      </p>
    </div>
  );
}
