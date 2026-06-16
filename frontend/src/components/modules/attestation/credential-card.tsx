"use client";

/**
 * Single Credential row card.
 *
 * Surfaces credential metadata, verification status, rejection feedback, and the
 * lifecycle actions (edit, delete, submit for verification). Each evidence file
 * is listed with a View action that fetches a short-lived presigned download URL
 * (owner-scoped) and opens it in a new tab.
 *
 * Maps to: FR-ATT credential verification lifecycle.
 */
import { useState } from "react";

import { CredentialStatusBadge } from "./credential-status-badge";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet } from "@/lib/generated/sdk.gen";
import type { CredentialResponse } from "@/lib/generated/types.gen";

/** Display the human-readable file name from an S3 object key. */
function keyDisplayName(key: string): string {
  const segments = key.split("/");
  return segments[segments.length - 1] || key;
}

type CredentialCardProps = {
  /** Credential record to render. */
  credential: CredentialResponse;
  /** Switch this credential into edit mode. */
  onEdit: (credential: CredentialResponse) => void;
  /** Delete this credential. */
  onDelete: (credentialId: string) => void;
  /** Submit this credential for verification review. */
  onSubmitForVerification: (credentialId: string) => void;
  /** Whether an action for this credential is in flight. */
  busy: boolean;
};

const SECONDARY_BUTTON =
  "min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60";

const DELETE_BUTTON =
  "min-h-12 rounded-xl border border-error/50 bg-error/5 px-6 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60";

const SUBMIT_BUTTON =
  "min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Render one Credential as a card with lifecycle actions.
 *
 * Submit-for-verification is only offered for credentials that have not yet been
 * accepted into review ("unverified" or "rejected") and is disabled until the
 * owner has provided at least one piece of verification evidence (an uploaded
 * file, a verification URL, or a reference number).
 *
 * @param credential - Credential to render.
 * @param onEdit - Edit affordance callback.
 * @param onDelete - Delete affordance callback.
 * @param onSubmitForVerification - Submit-for-verification callback.
 * @param busy - Disables actions while a request is in flight.
 */
export function CredentialCard({
  credential,
  onEdit,
  onDelete,
  onSubmitForVerification,
  busy,
}: CredentialCardProps) {
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  /**
   * Fetch a presigned download URL for one evidence file and open it.
   *
   * @param key - S3 object key of the evidence file to view.
   */
  async function handleViewEvidence(key: string) {
    setEvidenceError(null);
    setDownloadingKey(key);
    configureBrowserClient();
    const result =
      await downloadCredentialEvidenceV1CredentialsCredentialIdEvidenceGet({
        headers: getAccessTokenHeaders(),
        path: { credential_id: credential.id },
        query: { key },
      });
    setDownloadingKey(null);

    if (!result.response.ok || !result.data) {
      setEvidenceError(describeGeneratedError(result.error));
      return;
    }

    window.open(result.data.url, "_blank", "noopener,noreferrer");
  }

  const canSubmit =
    credential.evidence_file_keys.length > 0 ||
    Boolean(credential.verification_url) ||
    Boolean(credential.reference_number);

  const showSubmit =
    credential.verification_status === "unverified" ||
    credential.verification_status === "rejected";

  const showRejection =
    credential.verification_status === "rejected" &&
    Boolean(credential.rejection_reason);

  return (
    <article className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="font-heading text-lg font-bold text-foreground">
              {credential.title}
            </h3>
            <CredentialStatusBadge
              expired={credential.expired}
              status={credential.verification_status}
            />
          </div>
          <p className="text-sm text-foreground-muted">
            {credential.issuer} · issued {credential.issued_date}
            {credential.expires_date
              ? ` · expires ${credential.expires_date}`
              : ""}
          </p>
          {credential.credential_type ||
          credential.issuer_type ||
          credential.reference_number ? (
            <p className="text-sm text-foreground-muted">
              {[
                credential.credential_type,
                credential.issuer_type,
                credential.reference_number
                  ? `ref ${credential.reference_number}`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ) : null}
          <div className="grid gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              Evidence files
            </p>
            {credential.evidence_file_keys.length === 0 ? (
              <p className="text-sm text-foreground-muted">
                No evidence files attached.
              </p>
            ) : (
              <ul className="grid gap-2">
                {credential.evidence_file_keys.map((key) => (
                  <li
                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-default bg-surface-2 px-3 py-2"
                    key={key}
                  >
                    <span className="min-w-0 break-all text-sm text-foreground">
                      {keyDisplayName(key)}
                    </span>
                    <button
                      className="flex min-h-11 items-center justify-center rounded-lg border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={downloadingKey === key}
                      onClick={() => handleViewEvidence(key)}
                      type="button"
                    >
                      {downloadingKey === key ? "Opening…" : "View"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {evidenceError ? (
              <p className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">
                {evidenceError}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {showRejection ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {credential.rejection_reason}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          className={SECONDARY_BUTTON}
          disabled={busy}
          onClick={() => onEdit(credential)}
          type="button"
        >
          Edit
        </button>
        <button
          className={DELETE_BUTTON}
          disabled={busy}
          onClick={() => onDelete(credential.id)}
          type="button"
        >
          Delete
        </button>
        {showSubmit ? (
          <button
            className={SUBMIT_BUTTON}
            disabled={busy || !canSubmit}
            onClick={() => onSubmitForVerification(credential.id)}
            title={
              canSubmit
                ? undefined
                : "Add evidence, a verification URL, or a reference number before submitting."
            }
            type="button"
          >
            Submit for verification
          </button>
        ) : null}
      </div>
    </article>
  );
}
