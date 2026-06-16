"use client";

/**
 * KYC document upload form.
 *
 * Requests a constrained backend upload URL, uploads the selected document to
 * that URL, then submits the resulting S3 key for review. The backend enforces
 * MIME, size, ownership, and status transitions.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getKycStatusV1SettingsKycGet as getKycStatus,
  requestKycUploadUrl,
  submitKycUpload,
} from "@/lib/generated/sdk.gen";
import type { KycDocumentResponse } from "@/lib/generated/types.gen";

import { FormMessage } from "./form-message";

type KycDocType =
  | "drivers_license"
  | "national_id"
  | "passport"
  | "proof_of_address";

const documentTypes: Array<{ label: string; value: KycDocType }> = [
  { label: "Passport", value: "passport" },
  { label: "Driver's license", value: "drivers_license" },
  { label: "National ID", value: "national_id" },
  { label: "Proof of address", value: "proof_of_address" },
];

function formatDocTypeLabel(type: string): string {
  switch (type) {
    case "passport":
      return "Passport";
    case "drivers_license":
      return "Driver's license";
    case "national_id":
      return "National ID";
    case "proof_of_address":
      return "Proof of address";
    default:
      return type;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

/**
 * Render the authenticated KYC upload workflow.
 */
export function KycUpload() {
  const [docType, setDocType] = useState<KycDocType>("passport");
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  // Live KYC status states
  const [kycStatus, setKycStatus] = useState<string>("unverified");
  const [documents, setDocuments] = useState<KycDocumentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const canSubmit = file !== null;

  async function fetchStatus() {
    configureBrowserClient();
    try {
      const response = await getKycStatus({ headers: getAccessTokenHeaders() });
      if (response.response.ok && response.data) {
        setKycStatus(response.data.kyc_status);
        setDocuments(response.data.documents || []);
      }
    } catch (err) {
      console.error("Failed to load KYC status:", err);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
  }, []);

  async function submitKyc(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    if (!file) {
      setError("Choose a document before submitting.");
      return;
    }

    setIsSubmitting(true);
    configureBrowserClient();
    const uploadTarget = await requestKycUploadUrl({
      body: {
        doc_type: docType,
        file_size: file.size,
        mime_type: file.type || "application/octet-stream",
      },
      headers: getAccessTokenHeaders(),
    });

    if (!uploadTarget.response.ok || !uploadTarget.data) {
      setIsSubmitting(false);
      setError(describeGeneratedError(uploadTarget.error));
      return;
    }

    const uploadResponse = await fetch(uploadTarget.data.upload_url, {
      body: file,
      headers: {
        "Content-Type": file.type || "application/octet-stream",
      },
      method: "PUT",
    });

    if (!uploadResponse.ok) {
      setIsSubmitting(false);
      setError("Document upload failed.");
      return;
    }

    const submission = await submitKycUpload({
      body: { s3_key: uploadTarget.data.s3_key },
      headers: getAccessTokenHeaders(),
    });
    setIsSubmitting(false);

    if (!submission.response.ok) {
      setError(describeGeneratedError(submission.error));
      return;
    }

    setSuccess("Document submitted for review.");
    setFile(null);
    fetchStatus();
  }

  if (isLoading) {
    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center space-y-3" data-testid="loading">
        <svg className="h-8 w-8 animate-spin text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <span className="text-sm font-medium text-foreground-muted">Loading verification status...</span>
      </div>
    );
  }

  const hasRejectedDoc = documents.some((doc) => doc.status === "rejected");
  const latestRejectedDoc = [...documents]
    .filter((doc) => doc.status === "rejected")
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];

  return (
    <div className="space-y-6">
      {/* Live Status Header */}
      {kycStatus === "verified" && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-success/30 bg-success/5 p-6 text-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success text-white shadow-sm">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Identity Verified</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              Your identity verification is complete. Your account is fully eligible to publish licensed Frameworks and request payouts.
            </p>
          </div>
        </div>
      )}

      {kycStatus === "pending" && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-warning/30 bg-warning/5 p-6 text-center space-y-3 animate-pulse">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-warning text-white shadow-sm">
            <svg className="h-6 w-6 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Verification Pending</h3>
            <p className="text-sm text-foreground-muted max-w-md">
              Compliance is reviewing your document. This typically takes less than 24 hours. We will notify you once completed.
            </p>
          </div>
        </div>
      )}

      {kycStatus === "rejected" && latestRejectedDoc && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-error/30 bg-error/5 p-6 text-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-error text-white shadow-sm">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div className="space-y-1">
            <h3 className="font-heading text-lg font-bold text-foreground">Verification Rejected</h3>
            <p className="text-sm text-error font-medium max-w-md">
              Reason: {latestRejectedDoc.notes || "Please upload a clearer or more valid identity document."}
            </p>
          </div>
        </div>
      )}

      {/* Upload Form (only shown if not verified and not pending, OR if they need to upload/retry) */}
      {kycStatus !== "verified" && kycStatus !== "pending" && (
        <form className="space-y-5" onSubmit={submitKyc}>
          {error ? <FormMessage kind="error" message={error} /> : null}
          {success ? <FormMessage kind="success" message={success} /> : null}

          <label className="block" htmlFor="kyc-type">
            <span className="text-sm font-medium text-foreground">
              Document type
            </span>
            <select
              className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm text-foreground outline-none focus:outline-none focus-visible:outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
              id="kyc-type"
              onChange={(event) => setDocType(event.target.value as KycDocType)}
              value={docType}
            >
              {documentTypes.map((documentType) => (
                <option key={documentType.value} value={documentType.value}>
                  {documentType.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block" htmlFor="doc-upload">
            <span className="text-sm font-medium text-foreground">Document</span>
            <input
              accept="image/jpeg,image/png,application/pdf"
              className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm text-foreground outline-none focus:outline-none focus-visible:outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent file:mr-3 file:rounded-xl file:border-0 file:bg-foreground file:px-3 file:py-2 file:text-sm file:font-bold file:text-background file:cursor-pointer"
              id="doc-upload"
              name="kyc_document"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>

          <Button className="w-full" disabled={isSubmitting || !canSubmit} type="submit">
            {isSubmitting ? "Submitting document" : "Submit document"}
          </Button>
        </form>
      )}

      {/* History of Submitted Documents */}
      {documents.length > 0 && (
        <div className="space-y-3 border-t border-border-default pt-6">
          <h4 className="font-heading text-sm font-semibold text-foreground">Verification history</h4>
          <div className="space-y-2">
            {documents.map((doc) => {
              let statusBadge = "bg-foreground/10 text-foreground-muted";
              if (doc.status === "approved") {
                statusBadge = "bg-[#16A34A]/10 text-[#16A34A] border-[#16A34A]/20";
              } else if (doc.status === "pending") {
                statusBadge = "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/20";
              } else if (doc.status === "rejected") {
                statusBadge = "bg-[#DC2626]/10 text-[#DC2626] border-[#DC2626]/20";
              }

              return (
                <div key={doc.id} className="flex items-center justify-between rounded-xl bg-surface-2 p-3 border border-border-default text-xs">
                  <div className="space-y-1">
                    <p className="font-medium text-foreground">
                      {formatDocTypeLabel(doc.doc_type)}
                    </p>
                    <p className="text-foreground-subtle">
                      Submitted on {new Date(doc.created_at).toLocaleDateString()} • {formatFileSize(doc.file_size)}
                    </p>
                    {doc.status === "rejected" && doc.notes && (
                      <p className="text-error mt-1 italic">Reason: {doc.notes}</p>
                    )}
                  </div>
                  <span className={`rounded-badge border px-2 py-0.5 font-bold uppercase tracking-wider ${statusBadge}`}>
                    {doc.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
