"use client";

import { useState } from "react";
import { uploadOrgAttestorTaxDocument } from "@/lib/generated/sdk.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { useOrganization } from "@/components/modules/organizations/organization-context";

import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

export function TaxDocumentGate({
  application,
  onChange,
}: {
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const { orgId } = useOrganization();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState<"w9" | "w8ben" | "other">("w9");

  const isUploaded = !!application?.tax_document_key;

  if (isUploaded) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm text-sm text-foreground">
        Tax document uploaded successfully.
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

      onChange();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-semibold text-foreground">
            Document Type
          </label>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as "w9" | "w8ben" | "other")}
            className="w-full rounded-md border border-border-default bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="w9">W-9 (US Persons)</option>
            <option value="w8ben">W-8BEN (Non-US Persons)</option>
            <option value="other">Other / Exemption</option>
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
