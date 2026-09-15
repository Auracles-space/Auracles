"use client";

/**
 * Business-verification documents for one organization in the admin KYB queue.
 *
 * Links are presigned for 5 minutes and minting them writes an audit row, so
 * they load only when the admin asks and can be reloaded once they expire.
 *
 * Maps to: DESIGN-1; organizations end-to-end design, Slice D.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { adminOrgVerificationV1AdminOrgsOrgIdVerificationGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgDocumentLink } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

const CONTROL =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Render the on-demand document list for one pending organization.
 *
 * @param orgId - Organization whose submitted documents to show.
 */
export function AdminOrgKybDocuments({ orgId }: { orgId: string }) {
  const [documents, setDocuments] = useState<AdminOrgDocumentLink[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(): Promise<void> {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await adminOrgVerificationV1AdminOrgsOrgIdVerificationGet({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
    });
    setBusy(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setDocuments(result.data.documents);
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <button className={CONTROL} disabled={busy} onClick={() => void load()} type="button">
          {documents === null ? "Show documents" : "Reload links"}
        </button>
        <span className="text-xs text-foreground-muted">
          Links expire after 5 minutes. Opening documents is recorded in the audit log.
        </span>
      </div>
      {error ? <p className="text-sm text-error">{error}</p> : null}
      {documents !== null && documents.length === 0 ? (
        <p className="text-sm text-foreground-muted">No documents submitted.</p>
      ) : null}
      {documents !== null && documents.length > 0 ? (
        <ul className="grid gap-2">
          {documents.map((doc) => (
            <li
              className="flex flex-col gap-2 rounded-xl border border-border-default bg-surface-1 p-3 sm:flex-row sm:items-center sm:justify-between"
              key={`${doc.kind}-${doc.file_name}`}
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground">{formatLabel(doc.kind)}</p>
                <p className="break-all text-sm text-foreground-muted">{doc.file_name}</p>
              </div>
              {doc.download_url ? (
                <a
                  aria-label={`Open ${doc.file_name}`}
                  className={CONTROL}
                  href={doc.download_url}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  Open
                </a>
              ) : (
                <span className="text-sm text-foreground-muted">Not uploaded</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
