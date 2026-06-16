"use client";

/**
 * KYC document upload form.
 *
 * Requests a constrained backend upload URL, uploads the selected document to
 * that URL, then submits the resulting S3 key for review. The backend enforces
 * MIME, size, ownership, and status transitions.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { requestKycUploadUrl, submitKycUpload } from "@/lib/generated/sdk.gen";

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

/**
 * Render the authenticated KYC upload workflow.
 */
export function KycUpload() {
  const [docType, setDocType] = useState<KycDocType>("passport");
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const canSubmit = file !== null;

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
  }

  return (
    <form className="space-y-5" onSubmit={submitKyc}>
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Identity verification
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Submit a private document for payout eligibility review.
        </p>
      </div>
      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}

      <label className="block" htmlFor="doc-type">
        <span className="text-sm font-medium text-foreground">
          Document type
        </span>
        <select
          className="mt-2 min-h-12 w-full rounded-control border border-border-strong bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/15"
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
          className="mt-2 min-h-12 w-full rounded-control border border-border-strong bg-surface-2 px-4 py-2 text-sm text-foreground file:mr-3 file:rounded-control file:border-0 file:bg-foreground file:px-3 file:py-2 file:text-sm file:font-bold file:text-background"
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
  );
}
