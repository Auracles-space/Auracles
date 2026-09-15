"use client";

/**
 * Tax-document gate for the org attestor application checklist.
 *
 * Reserves an S3 upload session for the org's tax form, pushes the file to
 * the bucket, and confirms. A stored document is shown as on file (read from the
 * application, since the stepper remounts this gate on every visit) with a
 * replace action while the application is a draft or needs info; locked
 * read-only afterwards.
 *
 * Maps to: FR-ATT / org-attestor design (tax document gate).
 */
import { useState } from "react";
import { uploadOrgAttestorTaxDocument } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { useOrganization } from "@/components/modules/organizations/organization-context";

import {
  TAX_DOCUMENT_LABELS,
  taxDocumentLabel,
  taxDocumentTypesFor,
  type TaxDocumentType,
} from "@/lib/organizations/tax-documents";

import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

/**
 * Render the tax-document upload control for the checklist.
 *
 * @param application - The live application, or null before it exists.
 * @param onChange - Refetch callback fired after a successful upload.
 */
export function TaxDocumentGate({
  application,
  onChange,
}: {
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const { orgId, org } = useOrganization();
  const documentTypes = taxDocumentTypesFor(org?.country);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<TaxDocumentType>(documentTypes[0]);

  const isUploaded = !!application?.tax_document_key;
  // Only draft and needs-info applications may change their documents; once the
  // application is submitted or further along the tax document is locked.
  const canEdit =
    !application ||
    application.status === "draft" ||
    application.status === "needs_info";

  // Uploaded and locked: show the read-only confirmation.
  if (isUploaded && !canEdit) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm text-sm text-foreground">
        Tax document uploaded successfully.
      </div>
    );
  }

  // On file in an editable state (stored, or uploaded moments ago before the
  // refetch lands): confirm it and offer a replace instead of an empty form.
  if ((isUploaded || uploaded) && !replacing) {
    const typeLabel = taxDocumentLabel(application?.tax_document_type);
    return (
      <div className="rounded-xl border border-success/40 bg-success/10 p-5 text-sm text-foreground">
        <p className="font-semibold text-success">Tax document on file</p>
        {typeLabel ? <p className="mt-1 text-foreground-muted">{typeLabel}</p> : null}
        <button
          type="button"
          className="mt-3 min-h-11 text-sm font-semibold text-accent underline-offset-4 hover:underline"
          onClick={() => {
            setReplacing(true);
            setUploaded(false);
            setFile(null);
          }}
        >
          Replace document
        </button>
      </div>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Please select a file to upload.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      // Installs the step-up and refresh interceptors, so a 403 step-up
      // refusal prompts for 2FA instead of dead-ending on this form.
      configureBrowserClient();
      const res = await uploadOrgAttestorTaxDocument({
        path: { org_id: orgId },
        body: {
          tax_document_type: docType,
          file_name: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
        },
        headers: getAccessTokenHeaders(),
      });

      if (res.error || !res.data) {
        setError(describeGeneratedError(res.error));
        return;
      }

      // The session only reserves the S3 key; the file must still be pushed to
      // the bucket, or the admin download later resolves to a missing object.
      const form = new FormData();
      for (const [key, value] of Object.entries(res.data.fields)) {
        form.append(key, String(value));
      }
      form.append("file", file);
      const upload = await fetch(res.data.url, { method: "POST", body: form });
      if (!upload.ok) {
        setError("The upload could not be completed. Try again.");
        return;
      }

      setUploaded(true);
      setReplacing(false);
      onChange();
    } catch (caught) {
      setError(describeGeneratedError(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {isUploaded && (
        <div className="mb-4 rounded-lg border border-border-default bg-surface-2 p-3 text-sm text-foreground-muted">
          A tax document is already on file. Uploading a new one replaces it.
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="tax_document_type" className="mb-1 block text-sm font-semibold text-foreground">
            Document type
          </label>
          <select
            id="tax_document_type"
            value={docType}
            onChange={(e) => setDocType(e.target.value as TaxDocumentType)}
            className="w-full rounded-md border border-border-default bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent"
          >
            {documentTypes.map((value) => (
              <option key={value} value={value}>
                {TAX_DOCUMENT_LABELS[value]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="tax_document_file" className="mb-1 block text-sm font-semibold text-foreground">
            Upload Document (PDF/Image)
          </label>
          <input
            id="tax_document_file"
            type="file"
            accept=".pdf,image/*"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-foreground-muted file:mr-4 file:cursor-pointer file:rounded-md file:border-0 file:bg-foreground file:px-4 file:py-2 file:text-sm file:font-semibold file:text-background hover:file:bg-foreground/90"
          />
        </div>

        <div className="pt-2">
          <Button type="submit" disabled={loading || !file} loading={loading}>
            Upload Document
          </Button>
        </div>
      </form>
    </div>
  );
}
