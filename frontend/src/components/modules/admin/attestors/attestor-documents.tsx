"use client";

/**
 * Presigned document links (incorporation, tax) for one attestor application.
 *
 * Fetches fresh links on every mount because presigned URLs expire after 15
 * minutes; the card mounts this only while the admin has the section open.
 * Documents are never rendered inline.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listOrgAttestorDocumentsForAdmin } from "@/lib/generated/sdk.gen";
import type { OrgAttestorDocumentLink } from "@/lib/generated/types.gen";

type AttestorDocumentsProps = {
  applicationId: string;
};

/**
 * Render the review documents for one application as external links.
 *
 * @param props - The application whose documents to list.
 */
export function AttestorDocuments({ applicationId }: AttestorDocumentsProps) {
  const [documents, setDocuments] = useState<OrgAttestorDocumentLink[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      configureBrowserClient();
      const result = await listOrgAttestorDocumentsForAdmin({
        headers: getAccessTokenHeaders(),
        path: { application_id: applicationId },
      });
      if (cancelled) {
        return;
      }
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setDocuments([]);
        return;
      }
      setDocuments(result.data.documents);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [applicationId]);

  return (
    <div className="rounded-xl border border-border-default bg-surface-2 p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
        Review documents
      </p>
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
      {documents === null ? (
        <p className="mt-2 text-sm text-foreground-muted">Loading documents…</p>
      ) : documents.length === 0 ? (
        <p className="mt-2 text-sm text-foreground-muted">
          No documents uploaded for this application.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-border-default">
          {documents.map((doc) =>
            doc.available === false ? (
              <li
                className="flex min-h-11 flex-wrap items-center gap-2 py-2 text-sm"
                key={`${doc.label}-${doc.filename}`}
              >
                <span className="font-semibold text-foreground-muted">{doc.label}</span>
                <span className="break-all text-foreground-muted">{doc.filename}</span>
                <span className="rounded-badge border border-warning/30 bg-warning/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-warning">
                  Upload incomplete
                </span>
              </li>
            ) : (
              <li key={doc.url}>
                <a
                  className="flex min-h-11 flex-wrap items-center gap-2 py-2 text-sm font-medium text-accent underline-offset-4 hover:underline"
                  href={doc.url}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  <span className="font-semibold">{doc.label}</span>
                  <span className="break-all text-foreground">{doc.filename}</span>
                </a>
              </li>
            ),
          )}
        </ul>
      )}
      <p className="mt-2 text-xs text-foreground-muted">Links expire after 15 minutes.</p>
    </div>
  );
}
