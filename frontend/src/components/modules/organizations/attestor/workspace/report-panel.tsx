/**
 * Report submission panel for one attestation review workspace.
 *
 * Lets the assigned attestor upload private evidence and submit the final
 * structured determination.
 */

"use client";

import React, { useEffect, useState } from "react";
import {
  createAttestationEvidenceUpload,
  listRubricScores,
  submitAttestationReport
} from "@/lib/generated/sdk.gen";
import type { RubricScoreItem } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useRouter } from "next/navigation";

export interface ReportPanelProps {
  attestationId: string;
  canWrite: boolean;
  orgId: string;
}

// Mirrors the backend quality gate's `attestation_report_min_words` default.
// The gate sums rubric comment words + summary words + conditions words (scope
// is not counted). Kept in sync manually; the backend 422 remains the backstop
// if an admin overrides the platform config.
const MIN_REPORT_WORDS = 150;

/** Count whitespace-delimited words, matching Python's `str.split()`. */
function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

export function ReportPanel({ attestationId, canWrite, orgId }: ReportPanelProps) {
  const router = useRouter();
  const toast = useToast();

  const [outcome, setOutcome] = useState<"approved" | "conditional" | "rejected" | "">("");
  const [summary, setSummary] = useState("");
  const [scope, setScope] = useState("");
  const [conditions, setConditions] = useState("");

  const [evidenceFiles, setEvidenceFiles] = useState<File[]>([]);

  // Rubric comment words count toward the report-length gate, but live in a
  // separate tab. Fetch them so the word counter and submit gate mirror the
  // backend total exactly.
  const [rubricWords, setRubricWords] = useState(0);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await listRubricScores({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders(),
        });
        if (!active || res.error || !res.data) return;
        // Match the gate: only dimensions with both a score and a comment count.
        const words = res.data.scores.reduce(
          (sum: number, s: RubricScoreItem) =>
            s.score !== null && (s.comment ?? "").trim()
              ? sum + countWords(s.comment ?? "")
              : sum,
          0,
        );
        setRubricWords(words);
      } catch {
        // Non-fatal: the counter falls back to summary/conditions words and the
        // backend 422 still guards submission.
      }
    })();
    return () => {
      active = false;
    };
  }, [attestationId]);

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

    const { url, fields, s3_key: s3Key } = res.data;

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

    return s3Key;
  };

  // Mirror the backend contract's required fields (schemas.py): outcome set,
  // summary >= 20 chars, scope >= 10 chars, and conditions when the outcome is
  // conditional. Plus the quality gate's report-length minimum (rubric comment
  // words + summary words + conditions words >= 150). Gates the submit button so
  // an incomplete report is never sent.
  const conditionsRequired = outcome === "conditional";
  const totalWords =
    rubricWords +
    countWords(summary) +
    (conditionsRequired ? countWords(conditions) : 0);
  const meetsLength = totalWords >= MIN_REPORT_WORDS;
  const isValid =
    !!outcome &&
    summary.length >= 20 &&
    scope.length >= 10 &&
    (!conditionsRequired || conditions.trim().length > 0) &&
    meetsLength;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid) return;

    setIsSubmitting(true);
    setError(null);

    try {
      // Upload all files first
      const fileKeys: string[] = [];
      for (const file of evidenceFiles) {
        const fileKey = await uploadFile(file);
        fileKeys.push(fileKey);
      }

      // Submit report
      const res = await submitAttestationReport({
        path: { attestation_id: attestationId },
        body: {
          outcome: outcome as "approved" | "conditional" | "rejected",
          summary,
          scope,
          conditions: conditions || null,
          evidence_references:
            fileKeys.length > 0 ? { file_keys: fileKeys } : undefined,
        },
        headers: getAccessTokenHeaders()
      });

      if (res.error) {
        // Surface the quality-gate failures (e.g. incomplete rubric, open
        // clarification) so the reviewer knows exactly what to fix.
        throw new Error(describeGeneratedError(res.error));
      }

      // Success
      toast.success("Report submitted successfully.");
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
              placeholder="Conditions that must be met for full approval..."
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

        <div className="flex flex-col gap-3 pt-4 border-t border-border-default sm:flex-row sm:items-center sm:justify-between">
          <p
            className={`text-xs ${meetsLength ? "text-foreground-muted" : "text-error"}`}
          >
            Report length: {totalWords} / {MIN_REPORT_WORDS} words
            <span className="block text-foreground-muted">
              Rubric comments {rubricWords} + summary {countWords(summary)}
              {conditionsRequired ? ` + conditions ${countWords(conditions)}` : ""}
              {" "}(scope excluded).
            </span>
          </p>
          <Button
            type="submit"
            disabled={isSubmitting || !isValid}
            className="w-full sm:w-auto"
          >
            {isSubmitting ? "Submitting..." : "Submit Report"}
          </Button>
        </div>
      </form>
    </div>
  );
}
