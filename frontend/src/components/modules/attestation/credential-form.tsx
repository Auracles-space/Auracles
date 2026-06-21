"use client";

/**
 * Create / edit form for a user-owned Credential.
 *
 * Collects the durable credential record fields plus the verification metadata
 * (credential type, issuer type, verification URL, reference number) used by the
 * review lifecycle. In edit mode the form also hosts evidence file upload:
 * uploads are scoped to an existing credential_id (presigned S3 POST), and the
 * resulting object keys are merged into evidence_file_keys on save so the backend
 * scans/consumes them. Evidence upload is intentionally unavailable in create
 * mode because there is no credential_id to attach files to yet.
 *
 * Maps to: FR-ATT credential verification lifecycle.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { createCredentialEvidenceUploadSessionV1CredentialsCredentialIdUploadsPost } from "@/lib/generated/sdk.gen";
import type {
  CredentialCreateRequest,
  CredentialResponse,
} from "@/lib/generated/types.gen";

/** Accept attribute for the evidence file input (PDFs, docs, images). */
const EVIDENCE_ACCEPT =
  ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*";

/** Maximum credential evidence size enforced by the backend upload session. */
const MAX_EVIDENCE_SIZE_BYTES = 10 * 1024 * 1024;

/** Display the human-readable file name from an S3 object key. */
function keyDisplayName(key: string): string {
  const segments = key.split("/");
  return segments[segments.length - 1] || key;
}

/** Issuer-type values accepted by the backend taxonomy. */
type IssuerType = NonNullable<CredentialCreateRequest["issuer_type"]>;

/** Issuer-type select option values accepted by the backend. */
const ISSUER_TYPES: ReadonlyArray<IssuerType> = [
  "institution",
  "organisation",
  "government",
  "association",
];

const INPUT_CLASSES =
  "min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm font-medium text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent";

/** Normalised values emitted on submit (empty strings become null). */
export type CredentialFormValues = {
  title: string;
  issuer: string;
  issued_date: string;
  expires_date: string | null;
  credential_type: string | null;
  issuer_type: CredentialCreateRequest["issuer_type"];
  verification_url: string | null;
  reference_number: string | null;
  /**
   * Full set of evidence object keys to persist (existing + newly uploaded).
   * Only present in edit mode; omitted in create mode.
   */
  evidence_file_keys?: string[];
};

type CredentialFormProps = {
  /** Existing credential to pre-fill when editing. */
  initial?: CredentialResponse;
  /** Persist the collected values; resolves when the call completes. */
  onSubmit: (values: CredentialFormValues) => Promise<void>;
  /** Whether a submit is currently in flight. */
  submitting: boolean;
  /** Create a new record or edit an existing one. */
  mode: "create" | "edit";
};

/** Coerce a blank string to null for optional payload fields. */
function blankToNull(value: string): string | null {
  return value.trim() === "" ? null : value;
}

/**
 * Render the credential create/edit form.
 *
 * In edit mode, mutating identity-bearing fields on an already verified or
 * pending credential resets verification on the backend, so an inline warning
 * is surfaced before the user submits.
 *
 * @param initial - Credential to pre-fill in edit mode.
 * @param onSubmit - Callback receiving normalised form values.
 * @param submitting - Disables the submit button while a call is in flight.
 * @param mode - "create" or "edit".
 */
export function CredentialForm({
  initial,
  onSubmit,
  submitting,
  mode,
}: CredentialFormProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [issuer, setIssuer] = useState(initial?.issuer ?? "");
  const [issuedDate, setIssuedDate] = useState(initial?.issued_date ?? "");
  const [expiresDate, setExpiresDate] = useState(initial?.expires_date ?? "");
  const [credentialType, setCredentialType] = useState(
    initial?.credential_type ?? "",
  );
  const [issuerType, setIssuerType] = useState<IssuerType | "">(
    initial?.issuer_type &&
      ISSUER_TYPES.includes(initial.issuer_type as IssuerType)
      ? (initial.issuer_type as IssuerType)
      : "",
  );
  const [verificationUrl, setVerificationUrl] = useState(
    initial?.verification_url ?? "",
  );
  const [referenceNumber, setReferenceNumber] = useState(
    initial?.reference_number ?? "",
  );
  const [evidenceKeys, setEvidenceKeys] = useState<string[]>(
    initial?.evidence_file_keys ?? [],
  );
  const [uploading, setUploading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  const showEvidence = mode === "edit" && initial !== undefined;

  /**
   * Upload one evidence file via a presigned S3 POST session.
   *
   * Requests a scoped upload session for the existing credential, posts the file
   * directly to S3 (fields first, file last — required for presigned POST), and
   * stashes the returned object key in local state to be persisted on save.
   *
   * @param file - Selected file to upload as credential evidence.
   */
  async function handleEvidenceUpload(file: File) {
    if (!initial) {
      return;
    }
    if (file.size > MAX_EVIDENCE_SIZE_BYTES) {
      setEvidenceError("Evidence files must be 10 MB or smaller.");
      return;
    }
    setEvidenceError(null);
    setUploading(true);
    configureBrowserClient();

    const sessionResult =
      await createCredentialEvidenceUploadSessionV1CredentialsCredentialIdUploadsPost(
        {
          body: {
            content_type: file.type,
            file_name: file.name,
            size_bytes: file.size,
          },
          headers: getAccessTokenHeaders(),
          path: { credential_id: initial.id },
        },
      );

    if (!sessionResult.response.ok || !sessionResult.data) {
      setEvidenceError(describeGeneratedError(sessionResult.error));
      setUploading(false);
      return;
    }

    const session = sessionResult.data;
    const formData = new FormData();
    for (const [key, value] of Object.entries(session.fields)) {
      formData.append(key, String(value));
    }
    formData.append("file", file);

    try {
      const uploadResponse = await fetch(session.url, {
        body: formData,
        method: "POST",
      });
      if (!uploadResponse.ok) {
        setEvidenceError("Evidence upload failed before it could be saved.");
        setUploading(false);
        return;
      }
    } catch {
      setEvidenceError("Evidence upload failed before it could be saved.");
      setUploading(false);
      return;
    }

    setEvidenceKeys((current) =>
      current.includes(session.s3_key) ? current : [...current, session.s3_key],
    );
    setUploading(false);
  }

  /** Drop one pending/existing evidence key from the set to be saved. */
  function removeEvidenceKey(key: string) {
    setEvidenceKeys((current) => current.filter((item) => item !== key));
  }

  const showResetWarning =
    mode === "edit" &&
    (initial?.verification_status === "verified" ||
      initial?.verification_status === "pending");

  const canSubmit =
    title.trim() !== "" &&
    issuer.trim() !== "" &&
    issuedDate.trim() !== "" &&
    !submitting;

  /** Normalise field state and hand off to the parent submit handler. */
  async function handleSubmit() {
    await onSubmit({
      credential_type: blankToNull(credentialType),
      // Evidence keys are only meaningful when editing an existing credential.
      ...(showEvidence ? { evidence_file_keys: evidenceKeys } : {}),
      expires_date: blankToNull(expiresDate),
      issued_date: issuedDate,
      issuer,
      issuer_type: issuerType === "" ? null : issuerType,
      reference_number: blankToNull(referenceNumber),
      title,
      verification_url: blankToNull(verificationUrl),
    });
  }

  return (
    <div className="grid gap-4">
      {showResetWarning ? (
        <p className="rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
          Editing the title, issuer, issued date, or reference number will reset
          verification and require re-review.
        </p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Credential title
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setTitle(event.target.value)}
            value={title}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Issuer
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setIssuer(event.target.value)}
            value={issuer}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Issued date
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setIssuedDate(event.target.value)}
            type="date"
            value={issuedDate}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Expiry date
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setExpiresDate(event.target.value)}
            type="date"
            value={expiresDate ?? ""}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Credential type
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setCredentialType(event.target.value)}
            placeholder="e.g. Certification, Licence, Degree"
            value={credentialType}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Issuer type
          <select
            className={INPUT_CLASSES}
            onChange={(event) =>
              setIssuerType(event.target.value as IssuerType | "")
            }
            value={issuerType ?? ""}
          >
            <option value="">Select issuer type</option>
            {ISSUER_TYPES.map((option) => (
              <option key={option} value={option}>
                {option.charAt(0).toUpperCase() + option.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Verification URL
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setVerificationUrl(event.target.value)}
            placeholder="https://"
            type="url"
            value={verificationUrl}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Reference number
          <input
            className={INPUT_CLASSES}
            onChange={(event) => setReferenceNumber(event.target.value)}
            value={referenceNumber}
          />
        </label>
      </div>

      <div className="grid gap-3 rounded-xl border border-border-default bg-surface-2/40 p-4">
        <p className="text-sm font-semibold text-foreground">Evidence files</p>
        {showEvidence ? (
          <>
            <label className="grid gap-2 text-sm font-semibold text-foreground">
              Upload evidence
              <input
                accept={EVIDENCE_ACCEPT}
                aria-label="Upload evidence"
                className="min-h-12 rounded-xl border border-border-default bg-background px-4 py-3 text-sm font-medium text-foreground outline-none transition-colors file:mr-4 file:rounded-lg file:border-0 file:bg-foreground file:px-4 file:py-2 file:text-sm file:font-semibold file:text-background focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={uploading || submitting}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  // Reset so re-selecting the same file re-fires change.
                  event.target.value = "";
                  if (file) {
                    void handleEvidenceUpload(file);
                  }
                }}
                type="file"
              />
            </label>
            {uploading ? (
              <p className="text-xs font-medium text-foreground-muted">
                Uploading evidence…
              </p>
            ) : null}
            <p className="text-xs text-foreground-muted">
              PDF, Word, and image files up to 10 MB.
            </p>
            {evidenceError ? (
              <p className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">
                {evidenceError}
              </p>
            ) : null}
            {evidenceKeys.length > 0 ? (
              <ul className="grid gap-2">
                {evidenceKeys.map((key) => (
                  <li
                    className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-default bg-surface-2 px-3 py-2"
                    key={key}
                  >
                    <span className="min-w-0 break-all text-sm text-foreground">
                      {keyDisplayName(key)}
                    </span>
                    <button
                      aria-label={`Remove ${keyDisplayName(key)}`}
                      className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-border-default bg-surface-1 px-3 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={uploading || submitting}
                      onClick={() => removeEvidenceKey(key)}
                      type="button"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-foreground-muted">
                No evidence files attached yet.
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-foreground-muted">
            Save the credential first, then add evidence files.
          </p>
        )}
      </div>

      <button
        className="min-h-12 w-full rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 md:w-auto md:justify-self-start"
        disabled={!canSubmit}
        onClick={handleSubmit}
        type="button"
      >
        {mode === "create"
          ? submitting
            ? "Adding credential"
            : "Add credential"
          : submitting
            ? "Saving changes"
            : "Save changes"}
      </button>
    </div>
  );
}
