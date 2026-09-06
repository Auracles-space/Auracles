"use client";

/**
 * Identity verification panel.
 *
 * Manual review flow: the user uploads a government identity document straight
 * to private storage via a presigned POST, confirms it, and an Auracles admin
 * reviews it. The verdict arrives asynchronously and updates kyc_status, so the
 * panel re-reads status when the user tabs back.
 *
 * Documents are held privately by Auracles and are never shown publicly — only
 * a reviewing admin can open them, and every access is audited.
 *
 * Maps to: FR-AUTH-009, FR-SET-004.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { ensureBrowserAccessToken } from "@/lib/auth/current-user-session";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  confirmKycDocumentV1SettingsKycDocumentsDocumentIdConfirmPost as confirmKycDocument,
  getKycStatusV1SettingsKycGet as getKycStatus,
  requestKycDocumentUploadUrlV1SettingsKycDocumentsPost as requestKycUploadUrl,
} from "@/lib/generated/sdk.gen";
import type { KycDocumentResponse } from "@/lib/generated/types.gen";

import { FormMessage } from "./form-message";

/** Accepted identity document formats, mirroring the backend allow-list. */
const ACCEPTED_MIME_TYPES = ["image/jpeg", "image/png", "application/pdf"];

/** Maximum accepted document size, mirroring the backend ceiling (10 MB). */
const MAX_FILE_BYTES = 10 * 1024 * 1024;

/** Document types a user may submit, in the order most people reach for them. */
const DOC_TYPE_OPTIONS = [
  { value: "national_id", label: "National ID (e.g. NIN slip)" },
  { value: "passport", label: "Passport" },
  { value: "drivers_license", label: "Driver's licence" },
  { value: "proof_of_address", label: "Proof of address" },
] as const;

/** Human labels for the document type stored on each submission. */
const DOC_TYPE_LABELS: Record<string, string> = {
  drivers_license: "Driver's licence",
  national_id: "National ID",
  passport: "Passport",
  proof_of_address: "Proof of address",
};

/**
 * Describe a submitted document's current position in the review process.
 *
 * Scan state is deliberately folded into one user-facing line: a document that
 * is still being checked is not yet in front of a reviewer, and a quarantined
 * one never will be, so both need to read as "do something" rather than "wait".
 *
 * @param document - The submitted document to describe.
 * @returns A short status label and the tone to render it in.
 */
function describeDocument(document: KycDocumentResponse): {
  label: string;
  tone: "success" | "error" | "muted";
} {
  if (document.scan_status === "quarantined") {
    return { label: "Could not be processed — please upload it again", tone: "error" };
  }
  if (document.scan_status === "pending_scan") {
    return { label: "Checking file…", tone: "muted" };
  }
  if (document.status === "verified") {
    return { label: "Accepted", tone: "success" };
  }
  if (document.status === "rejected") {
    return { label: "Not accepted", tone: "error" };
  }
  return { label: "Awaiting review", tone: "muted" };
}

/**
 * Format a byte count for display next to a submitted document.
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
 * Render the authenticated identity-verification workflow.
 */
export function KycUpload() {
  const [kycStatus, setKycStatus] = useState<string>("unverified");
  const [documents, setDocuments] = useState<KycDocumentResponse[]>([]);
  const [docType, setDocType] = useState<string>(DOC_TYPE_OPTIONS[0].value);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const fetchStatus = useCallback(async () => {
    configureBrowserClient();
    // After a page reload the access token is gone (memory-only); rehydrate it
    // from the refresh cookie before calling the API, or the status read 401s.
    const hasToken = await ensureBrowserAccessToken();
    if (!hasToken) {
      setIsLoading(false);
      return;
    }
    try {
      const response = await getKycStatus({ headers: getAccessTokenHeaders() });
      if (response.response.ok && response.data) {
        setKycStatus(response.data.kyc_status);
        setDocuments(response.data.documents);
      }
    } catch {
      console.error("Failed to load verification status");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // The verdict is asynchronous (an admin reviews, then kyc_status changes) and
  // the scan resolves within seconds of upload. Re-read on focus so a returning
  // user sees current truth without a manual refresh.
  useEffect(() => {
    function refetchOnReturn() {
      if (document.visibilityState === "visible") {
        fetchStatus();
      }
    }
    window.addEventListener("focus", refetchOnReturn);
    document.addEventListener("visibilitychange", refetchOnReturn);
    return () => {
      window.removeEventListener("focus", refetchOnReturn);
      document.removeEventListener("visibilitychange", refetchOnReturn);
    };
  }, [fetchStatus]);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0] ?? null;
    setError(null);
    setNotice(null);
    if (file === null) {
      setSelectedFile(null);
      return;
    }
    // Validate before the round trip so the user is corrected immediately
    // rather than after an upload that the backend would refuse anyway.
    if (!ACCEPTED_MIME_TYPES.includes(file.type)) {
      setSelectedFile(null);
      setError("Upload a JPG, PNG, or PDF.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setSelectedFile(null);
      setError("That file is larger than 10 MB. Try a smaller photo or scan.");
      return;
    }
    setSelectedFile(file);
  }

  async function submitDocument(): Promise<void> {
    if (selectedFile === null) {
      return;
    }
    setError(null);
    setNotice(null);
    setIsUploading(true);
    configureBrowserClient();
    await ensureBrowserAccessToken();
    try {
      const target = await requestKycUploadUrl({
        body: {
          doc_type: docType as (typeof DOC_TYPE_OPTIONS)[number]["value"],
          filename: selectedFile.name,
          mime_type: selectedFile.type,
          file_size: selectedFile.size,
        },
        headers: getAccessTokenHeaders(),
      });
      if (target.error || !target.data) {
        setError(describeGeneratedError(target.error));
        return;
      }

      const form = new FormData();
      for (const [key, value] of Object.entries(target.data.fields)) {
        form.append(key, String(value));
      }
      // S3 ignores anything after the file part, so it must be appended last.
      form.append("file", selectedFile);
      const upload = await fetch(target.data.upload_url, {
        method: "POST",
        body: form,
      });
      if (!upload.ok) {
        setError("The upload could not be completed. Try again.");
        return;
      }

      const confirmed = await confirmKycDocument({
        path: { document_id: target.data.document_id },
        headers: getAccessTokenHeaders(),
      });
      if (confirmed.error || !confirmed.data) {
        setError(describeGeneratedError(confirmed.error));
        return;
      }

      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      setNotice("Document submitted. We'll review it and let you know.");
      await fetchStatus();
    } catch {
      setError("We couldn't submit your document. Try again in a moment.");
    } finally {
      setIsUploading(false);
    }
  }

  if (isLoading) {
    return (
      <div
        className="flex min-h-[200px] flex-col items-center justify-center space-y-3"
        data-testid="loading"
      >
        <svg className="h-8 w-8 animate-spin text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <span className="text-sm font-medium text-foreground-muted">
          Loading verification status…
        </span>
      </div>
    );
  }

  const isVerified = kycStatus === "verified";
  const isRejected = kycStatus === "rejected";
  // Only a settled approval closes submission. Someone under review may still
  // add a clearer document, and a rejection is usually a correctable one.
  const canSubmit = !isVerified;

  return (
    <div className="space-y-6">
      {isVerified && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-success/30 bg-success/5 p-6 text-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-success text-white">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Identity Verified</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              Your identity is verified. Your account is fully eligible to publish licensed Frameworks and request payouts.
            </p>
          </div>
        </div>
      )}

      {kycStatus === "pending" && (
        <div className="flex flex-col items-center justify-center space-y-3 rounded-xl border border-warning/30 bg-warning/5 p-6 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-warning text-white">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Verification In Review</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              Your document is with our review team. This usually takes one business day, and we&apos;ll notify you as soon as there&apos;s a decision.
            </p>
          </div>
        </div>
      )}

      {isRejected && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-error/30 bg-error/5 p-6 text-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-error text-white">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Verification Didn&apos;t Pass</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              We couldn&apos;t confirm your identity from the document you sent. Make sure it&apos;s in focus, fully in frame, and well-lit, then submit it again.
            </p>
          </div>
        </div>
      )}

      {documents.length > 0 && (
        <section
          aria-labelledby="kyc-documents-heading"
          className="rounded-xl border border-border-default bg-surface-2 p-4 sm:p-6"
        >
          <h3
            className="font-heading text-base font-bold text-foreground"
            id="kyc-documents-heading"
          >
            Documents you&apos;ve submitted
          </h3>
          <ul className="mt-4 space-y-3">
            {documents.map((document) => {
              const described = describeDocument(document);
              return (
                <li
                  className="flex flex-col gap-1 rounded-xl border border-border-default bg-background px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
                  key={document.id}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-foreground">
                      {DOC_TYPE_LABELS[document.doc_type] ?? document.doc_type}
                    </p>
                    <p className="text-xs text-foreground-muted">
                      {formatFileSize(document.file_size)} ·{" "}
                      {new Date(document.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <p
                    className={[
                      "text-xs font-semibold sm:text-right",
                      described.tone === "success"
                        ? "text-success"
                        : described.tone === "error"
                          ? "text-error"
                          : "text-foreground-muted",
                    ].join(" ")}
                  >
                    {described.label}
                  </p>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {canSubmit && (
        <div className="rounded-xl border border-border-default bg-surface-2 p-4 sm:p-6 space-y-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">
              {documents.length > 0 ? "Submit another document" : "Verify your identity"}
            </h3>
            <p className="text-sm text-foreground-muted">
              Upload a clear photo or scan of a government-issued ID. Our team reviews it privately — your document is never published, and only a reviewer can open it.
            </p>
          </div>

          {error ? <FormMessage kind="error" message={error} /> : null}
          {notice ? <FormMessage kind="success" message={notice} /> : null}

          <div className="space-y-2">
            <label
              className="block text-sm font-semibold text-foreground"
              htmlFor="kyc-doc-type"
            >
              Document type
            </label>
            <Select
              id="kyc-doc-type"
              onChange={(event) => setDocType(event.target.value)}
              value={docType}
            >
              {DOC_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <label
              className="block text-sm font-semibold text-foreground"
              htmlFor="kyc-file"
            >
              Document file
            </label>
            <input
              accept={ACCEPTED_MIME_TYPES.join(",")}
              className="block w-full cursor-pointer rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors file:mr-4 file:cursor-pointer file:rounded-lg file:border-0 file:bg-surface-2 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
              id="kyc-file"
              onChange={handleFileChange}
              ref={fileInputRef}
              type="file"
            />
            <p className="text-xs text-foreground-muted">
              JPG, PNG, or PDF, up to 10 MB.
            </p>
          </div>

          <Button
            className="w-full"
            disabled={selectedFile === null}
            loading={isUploading}
            onClick={submitDocument}
            type="button"
          >
            {isUploading ? "Submitting…" : "Submit for review"}
          </Button>
        </div>
      )}
    </div>
  );
}
