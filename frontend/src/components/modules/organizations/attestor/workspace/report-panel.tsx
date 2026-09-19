/**
 * Report submission panel for one attestation review workspace.
 *
 * Lets the assigned attestor upload private evidence and submit the final
 * structured determination. Outside the two submittable states the form is
 * replaced by a line saying who is holding the report now — waiting
 * requestor, admin dispute review, or settled — because "already submitted"
 * told a reviewer nothing about what happens next.
 */

"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { RUBRIC_SAVED_EVENT } from "@/lib/attestation/workspace-events";
import {
  getAttestationReportDraft,
  listRubricScores,
  saveAttestationReportDraft,
  submitAttestationReport
} from "@/lib/generated/sdk.gen";
import {
  ReportEvidenceUploader,
  type EvidenceSelection,
} from "./report-evidence-uploader";
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
  /** Current attestation status; the form is editable only while submittable. */
  status?: string;
  /** Quiet period before an edit is autosaved; shortened in tests. */
  draftSaveDelayMs?: number;
}

// Statuses the backend accepts a report submission in (report.py). Outside
// these (e.g. already report_submitted, disputed, resolved) the form is locked
// so a resubmit can't 409.
const SUBMITTABLE_STATUSES = ["in_review", "revision_requested"];

/**
 * Explain who holds the report while the form is locked.
 *
 * @param status - Current attestation status.
 */
function describeLockedState(status: string): string {
  if (status === "report_submitted") {
    return "Your report is with the requestor. They can accept it or raise a dispute until the dispute window closes.";
  }
  if (status === "disputed") {
    return "The requestor disputed this report. An admin is reviewing it — if they ask for a revision, this form reopens.";
  }
  return "This attestation is closed. The report can no longer be edited.";
}

// Long enough that autosave does not fire on every keystroke, short enough
// that a reviewer who closes the tab mid-sentence loses nothing that matters.
const DEFAULT_DRAFT_SAVE_DELAY_MS = 1200;

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

export function ReportPanel({
  attestationId,
  canWrite,
  orgId,
  status = "in_review",
  draftSaveDelayMs = DEFAULT_DRAFT_SAVE_DELAY_MS,
}: ReportPanelProps) {
  const router = useRouter();
  const toast = useToast();

  const [outcome, setOutcome] = useState<"approved" | "conditional" | "rejected" | "">("");
  const [summary, setSummary] = useState("");
  const [scope, setScope] = useState("");
  const [conditions, setConditions] = useState("");

  // Evidence is uploaded and virus-checked by the child as files are chosen,
  // so submission only carries keys that already came back clean. An empty
  // selection is settled: a report needs no evidence.
  const [evidence, setEvidence] = useState<EvidenceSelection>({
    fileKeys: [],
    settled: true,
  });

  // Rubric comment words count toward the report-length gate, but live in a
  // separate tab. Fetch them so the word counter and submit gate mirror the
  // backend total exactly.
  const [rubricWords, setRubricWords] = useState(0);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The report is written across sittings, so it is saved server-side as the
  // reviewer types. Editing only starts once the saved draft has been read
  // back, otherwise an empty form would autosave over the saved work.
  const [draftLoaded, setDraftLoaded] = useState(false);
  // A reviewer can start typing before the saved draft comes back; their words
  // win over whatever the server was still fetching.
  const editedRef = useRef(false);
  const [draftState, setDraftState] = useState<"idle" | "saving" | "saved">("idle");
  const editable = canWrite && SUBMITTABLE_STATUSES.includes(status);

  useEffect(() => {
    if (!editable) return;
    let active = true;
    /** Read back whatever the reviewer had already written. */
    async function loadDraft() {
      try {
        const res = await getAttestationReportDraft({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders(),
        });
        if (!active) return;
        if (!res.error && res.data && !editedRef.current) {
          const draft = res.data;
          if (draft.outcome) {
            setOutcome(draft.outcome as "approved" | "conditional" | "rejected");
          }
          setSummary(draft.summary ?? "");
          setScope(draft.scope ?? "");
          setConditions(draft.conditions ?? "");
        }
      } catch {
        // Non-fatal: the reviewer starts from a blank form and autosave still
        // runs, so nothing written from here on is lost.
      } finally {
        if (active) setDraftLoaded(true);
      }
    }
    void loadDraft();
    return () => {
      active = false;
    };
  }, [attestationId, editable]);

  useEffect(() => {
    if (!editable || !draftLoaded || isSubmitting) return;
    const handle = setTimeout(() => {
      /** Persist the current fields; failures stay silent and retry on the next edit. */
      async function saveDraft() {
        setDraftState("saving");
        try {
          const res = await saveAttestationReportDraft({
            path: { attestation_id: attestationId },
            body: { outcome: outcome || null, summary, scope, conditions },
            headers: getAccessTokenHeaders(),
          });
          setDraftState(res.error ? "idle" : "saved");
        } catch {
          setDraftState("idle");
        }
      }
      void saveDraft();
    }, draftSaveDelayMs);
    return () => clearTimeout(handle);
  }, [
    attestationId,
    conditions,
    draftLoaded,
    draftSaveDelayMs,
    editable,
    isSubmitting,
    outcome,
    scope,
    summary,
  ]);

  useEffect(() => {
    let active = true;
    /** Re-read rubric comment words; called on mount and after every rubric save. */
    async function loadRubricWords() {
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
    }
    void loadRubricWords();
    // Comments are written in the rubric panel after this panel mounts, so a
    // one-off read left the counter stuck at the mount-time total.
    const onRubricSaved = () => void loadRubricWords();
    window.addEventListener(RUBRIC_SAVED_EVENT, onRubricSaved);
    return () => {
      active = false;
      window.removeEventListener(RUBRIC_SAVED_EVENT, onRubricSaved);
    };
  }, [attestationId]);


  // Mirror the backend contract: outcome set; summary and scope present
  // (non-empty required fields); conditions present when the outcome is
  // conditional. Report body length is governed by the quality gate's word
  // minimum (rubric comment words + summary words + conditions words >= 150),
  // not by any per-field character floor. Gates the submit button so an
  // incomplete report is never sent.
  const conditionsRequired = outcome === "conditional";
  const totalWords =
    rubricWords +
    countWords(summary) +
    (conditionsRequired ? countWords(conditions) : 0);
  const meetsLength = totalWords >= MIN_REPORT_WORDS;
  const isValid =
    !!outcome &&
    summary.trim().length > 0 &&
    scope.trim().length > 0 &&
    (!conditionsRequired || conditions.trim().length > 0) &&
    meetsLength &&
    evidence.settled;

  const handleEvidenceChange = useCallback((selection: EvidenceSelection) => {
    setEvidence(selection);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const fileKeys = evidence.fileKeys;
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
      router.push(`/dashboard/organizations/${orgId}/attestor/queue`);
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

  // Once the report is in (or the attestation moved past the review states),
  // lock the form so a resubmit can't 409. Revision requests reopen it.
  if (!SUBMITTABLE_STATUSES.includes(status)) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-5 text-center space-y-2 shadow-sm">
        <h2 className="text-lg font-semibold text-foreground">Final report</h2>
        <p className="text-sm text-foreground-muted">
          {describeLockedState(status)}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 space-y-6 shadow-sm">
      <div>
        <h2 className="text-xl font-semibold text-foreground">Final report</h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Submit your final evaluation. This completes your part of the
          attestation and sends the report to the requestor.
        </p>
      </div>

      {status === "revision_requested" && (
        <p className="rounded-xl bg-surface-2 p-4 text-sm text-foreground">
          An admin asked for a revision. Update the report below and submit it
          again — the requestor sees only the resubmitted version.
        </p>
      )}

      {error && (
        <div className="p-4 text-sm text-error bg-error/5 rounded-xl border border-error/50">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Outcome <span className="text-error">*</span></label>
          <Select value={outcome} onChange={(e) => {
              editedRef.current = true;
              setOutcome(e.target.value as "approved" | "conditional" | "rejected");
            }} required>
            <option value="" disabled>Select an outcome...</option>
            <option value="approved">Approved</option>
            <option value="conditional">Conditional Approval</option>
            <option value="rejected">Rejected</option>
          </Select>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Summary <span className="text-error">*</span></label>
          <p className="text-xs text-foreground-muted mb-2">Required. Counts toward the report length below.</p>
          <Textarea
            value={summary}
            onChange={(e) => {
              editedRef.current = true;
              setSummary(e.target.value);
            }}
            required
            className="min-h-[100px]"
            placeholder="This framework demonstrates excellent compliance with..."
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Scope <span className="text-error">*</span></label>
          <p className="text-xs text-foreground-muted mb-2">Required. What was reviewed and its limitations — not counted toward report length.</p>
          <Textarea
            value={scope}
            onChange={(e) => {
              editedRef.current = true;
              setScope(e.target.value);
            }}
            required
            className="min-h-[100px]"
            placeholder="Review covered version 2.1 of the framework..."
          />
        </div>

        {outcome === "conditional" && (
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Conditions <span className="text-error">*</span></label>
            <p className="text-xs text-foreground-muted mb-2">Required for a conditional outcome. Counts toward the report length below.</p>
            <Textarea
              value={conditions}
              onChange={(e) => {
                editedRef.current = true;
                setConditions(e.target.value);
              }}
              required
              className="min-h-[100px]"
              placeholder="Conditions that must be met for full approval..."
            />
          </div>
        )}

        <ReportEvidenceUploader
          attestationId={attestationId}
          disabled={isSubmitting}
          onChange={handleEvidenceChange}
        />

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
          {draftState !== "idle" && (
            <p className="text-xs text-foreground-muted">
              {draftState === "saving" ? "Saving…" : "Draft saved"}
            </p>
          )}
          {!evidence.settled && (
            <p className="text-xs text-foreground-muted">
              Waiting for the evidence check to finish.
            </p>
          )}
          <Button
            type="submit"
            disabled={isSubmitting || !isValid}
            className="w-full sm:w-auto"
          >
            {isSubmitting ? "Submitting..." : "Submit report"}
          </Button>
        </div>
      </form>
    </div>
  );
}
