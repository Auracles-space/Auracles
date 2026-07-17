"use client";

import React, { useState } from "react";
import { 
  createAttestationEvidenceUpload,
  submitAttestationReport
} from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { useRouter } from "next/navigation";

export interface ReportPanelProps {
  attestationId: string;
  canWrite: boolean;
  orgId: string;
}

export function ReportPanel({ attestationId, canWrite, orgId }: ReportPanelProps) {
  const router = useRouter();
  
  const [outcome, setOutcome] = useState<"approved" | "conditional" | "rejected" | "">("");
  const [summary, setSummary] = useState("");
  const [scope, setScope] = useState("");
  const [conditions, setConditions] = useState("");

  const [evidenceFiles, setEvidenceFiles] = useState<File[]>([]);
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setEvidenceFiles(Array.from(e.target.files));
    }
  };

  const uploadFile = async (file: File): Promise<string> => {
    // 1. Get presigned URL
    const res = await createAttestationEvidenceUpload({
      path: { attestation_id: attestationId },
      body: {
        file_name: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size
      },
      headers: getAccessTokenHeaders()
    });

    if (res.error || !res.data) {
      throw new Error("Failed to get upload session for " + file.name);
    }

    const { url, fields, id } = res.data;

    // 2. Upload to S3
    const formData = new FormData();
    Object.entries(fields || {}).forEach(([key, value]) => {
      formData.append(key, value as string);
    });
    formData.append("file", file);

    const s3Res = await fetch(url, {
      method: "POST",
      body: formData,
    });

    if (!s3Res.ok) {
      throw new Error("Failed to upload " + file.name + " to storage.");
    }

    return id;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!outcome || !summary || !scope) return;
    
    setIsSubmitting(true);
    setError(null);

    try {
      // Upload all files first
      const references: Record<string, string> = {};
      for (const file of evidenceFiles) {
        const uploadId = await uploadFile(file);
        references[file.name] = uploadId;
      }

      // Submit report
      const res = await submitAttestationReport({
        path: { attestation_id: attestationId },
        body: {
          outcome: outcome as "approved" | "conditional" | "rejected",
          summary,
          scope,
          conditions: conditions || null,
          evidence_references: Object.keys(references).length > 0 ? references : undefined
        },
        headers: getAccessTokenHeaders()
      });

      if (res.error) {
        throw new Error("Failed to submit report.");
      }

      // Success
      alert("Report submitted successfully.");
      router.push(`/dashboard/organizations/${orgId}/queue`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!canWrite) {
    return (
      <div className="rounded-xl border border-dashed border-border-default p-8 text-center text-foreground-muted text-sm">
        Report submission is only available to the assigned attestor.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-elevated p-6 space-y-6 shadow-bento">
      <div>
        <h2 className="text-xl font-semibold text-foreground">Final Report</h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Submit your final evaluation. This will complete the attestation process.
        </p>
      </div>

      {error && (
        <div className="p-4 text-sm text-error bg-error/5 rounded-xl border border-error/50">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Outcome <span className="text-error">*</span></label>
          <Select value={outcome} onChange={(e) => setOutcome(e.target.value as "approved" | "conditional" | "rejected")} required>
            <option value="" disabled>Select an outcome...</option>
            <option value="approved">Approved</option>
            <option value="conditional">Conditional Approval</option>
            <option value="rejected">Rejected</option>
          </Select>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Summary <span className="text-error">*</span></label>
          <p className="text-xs text-foreground-muted mb-2">Provide a high-level summary of your findings (min 20 chars).</p>
          <Textarea 
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            required
            minLength={20}
            className="min-h-[100px]"
            placeholder="This framework demonstrates excellent compliance with..."
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Scope <span className="text-error">*</span></label>
          <p className="text-xs text-foreground-muted mb-2">Define what was reviewed and the limitations of this attestation.</p>
          <Textarea 
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            required
            minLength={10}
            className="min-h-[100px]"
            placeholder="Review covered version 2.1 of the framework..."
          />
        </div>

        {outcome === "conditional" && (
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Conditions</label>
            <p className="text-xs text-foreground-muted mb-2">What conditions must be met for full approval?</p>
            <Textarea 
              value={conditions}
              onChange={(e) => setConditions(e.target.value)}
              required
              className="min-h-[100px]"
            />
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Evidence Files (Optional)</label>
          <p className="text-xs text-foreground-muted mb-2">Attach any supporting documents (PDFs, spreadsheets).</p>
          <input 
            type="file" 
            multiple 
            onChange={handleFileChange}
            className="block w-full text-sm text-foreground-muted file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-foreground file:text-background hover:file:bg-foreground/90 transition-colors"
          />
          {evidenceFiles.length > 0 && (
            <ul className="mt-2 text-sm text-foreground-muted list-disc list-inside">
              {evidenceFiles.map(f => (
                <li key={f.name}>{f.name} ({(f.size / 1024).toFixed(1)} KB)</li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex justify-end pt-4 border-t border-border-default">
          <Button type="submit" disabled={isSubmitting || !outcome || !summary || !scope}>
            {isSubmitting ? "Submitting..." : "Submit Report"}
          </Button>
        </div>
      </form>
    </div>
  );
}
