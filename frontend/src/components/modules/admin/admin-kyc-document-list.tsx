"use client";

/**
 * Submitted identity documents for one user, inside the admin KYC review form.
 *
 * Loads the documents a user submitted and opens them behind short-lived
 * presigned URLs. Files are never proxied through the app and are never
 * embedded in the page — each open is a fresh, audited request.
 *
 * Maps to: FR-AUTH-009, FR-SET-011.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  downloadUserKycDocumentV1AdminUsersUserIdKycDocumentsDocumentIdDownloadGet as downloadKycDocument,
  listUserKycDocumentsV1AdminUsersUserIdKycDocumentsGet as listKycDocuments,
} from "@/lib/generated/sdk.gen";
import type { AdminKycDocumentResponse } from "@/lib/generated/types.gen";

/** Human labels for the document type stored on each submission. */
const DOC_TYPE_LABELS: Record<string, string> = {
  drivers_license: "Driver's licence",
  national_id: "National ID",
  passport: "Passport",
  proof_of_address: "Proof of address",
};

type AdminKycDocumentListProps = {
  /** The user whose submitted documents are under review. */
  userId: string;
};

/**
 * Format a byte count for display next to a document.
 *
 * @param bytes - Size in bytes.
 * @returns A short human-readable size.
 */
function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Render the identity documents a user submitted, with per-document open links.
 *
 * @param props - The user whose documents are being reviewed.
 */
export function AdminKycDocumentList({ userId }: AdminKycDocumentListProps) {
  const [documents, setDocuments] = useState<AdminKycDocumentResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadDocuments(): Promise<void> {
      configureBrowserClient();
      const result = await listKycDocuments({
        headers: getAccessTokenHeaders(),
        path: { user_id: userId },
      });
      if (!mounted) {
        return;
      }
      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setDocuments(result.data.documents);
    }

    void loadDocuments();
    return () => {
      mounted = false;
    };
  }, [userId]);

  const openDocument = useCallback(
    async (documentId: string): Promise<void> => {
      setError(null);
      setOpeningId(documentId);
      configureBrowserClient();
      const result = await downloadKycDocument({
        headers: getAccessTokenHeaders(),
        path: { document_id: documentId, user_id: userId },
      });
      setOpeningId(null);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      // noopener keeps the opened tab from reaching back into the admin session.
      window.open(result.data.download_url, "_blank", "noopener,noreferrer");
    },
    [userId],
  );

  if (loading) {
    return (
      <p className="text-sm text-foreground-muted">Loading submitted documents…</p>
    );
  }

  return (
    <div className="grid gap-3">
      <h4 className="text-sm font-semibold text-foreground">
        Submitted documents
      </h4>

      {error ? (
        <p
          className="rounded-xl border border-error/30 bg-error/10 px-4 py-3 text-sm text-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {documents.length === 0 ? (
        // A decision with nothing to look at is legitimate — this endpoint is
        // also the appeals override — but the reviewer should know that is what
        // they are doing.
        <p className="rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-foreground-muted">
          This user has not submitted any documents. Approving now is an override
          based on evidence gathered elsewhere.
        </p>
      ) : (
        <ul className="grid gap-2">
          {documents.map((document) => {
            const isClean = document.scan_status === "clean";
            return (
              <li
                className="flex flex-col gap-2 rounded-xl border border-border-default bg-background px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                key={document.id}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-foreground">
                    {DOC_TYPE_LABELS[document.doc_type] ?? document.doc_type}
                  </p>
                  <p className="text-xs text-foreground-muted">
                    {formatFileSize(document.file_size)} ·{" "}
                    {new Date(document.created_at).toLocaleDateString()} ·{" "}
                    {document.status}
                  </p>
                </div>
                {isClean ? (
                  <Button
                    className="min-h-10 px-4"
                    disabled={openingId === document.id}
                    onClick={() => void openDocument(document.id)}
                    variant="secondary"
                  >
                    {openingId === document.id ? "Opening…" : "Open"}
                  </Button>
                ) : (
                  <span className="text-xs font-semibold text-warning">
                    {document.scan_status === "quarantined"
                      ? "Blocked by virus scan"
                      : "Virus scan in progress"}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
