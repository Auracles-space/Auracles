"use client";

/**
 * Contributor pipeline status panel.
 *
 * Converts backend Artifact status fields into human-readable gate checks for
 * publish readiness. The backend remains the source of truth for enforcement.
 */
import { FormEvent, useState } from "react";

import { isLengthBetween } from "@/lib/forms/validators";
import { formatFrameworkStatus } from "@/lib/marketplace/format";
import { acknowledgeSimilarityNotice } from "@/lib/generated/sdk.gen";
import type { ArtifactResponse, FrameworkResponse } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type PipelineStatusPanelProps = {
  artifacts: ArtifactResponse[];
  frameworkId: string;
  frameworkStatus: FrameworkResponse["status"];
};

type PipelineCheck = {
  description: string;
  label: string;
  state: "pass" | "pending" | "fail" | "notice" | "idle";
  value: string;
};

/**
 * Build the pipeline status matrix shown to Contributors.
 *
 * @param artifacts - Artifacts currently attached to the Framework.
 * @param frameworkStatus - Current Framework workflow status.
 * @returns Ordered pipeline checks.
 */
export function buildPipelineChecks(
  artifacts: ArtifactResponse[],
  frameworkStatus: FrameworkResponse["status"],
): PipelineCheck[] {
  const hasArtifacts = artifacts.length > 0;
  const hasInfected = artifacts.some((artifact) => artifact.scan_status === "infected");
  const hasScanError = artifacts.some((artifact) => artifact.scan_status === "error");
  const allClean = hasArtifacts && artifacts.every((artifact) => artifact.scan_status === "clean");
  const anyPiiReview = artifacts.some((artifact) => artifact.pii_review_needed);
  const allProcessed =
    hasArtifacts &&
    artifacts.every((artifact) => artifact.processing_status === "processed");
  const anyNearDuplicate = artifacts.some(
    (artifact) => artifact.near_duplicate_blocked,
  );
  const hasSimilarityNotice = artifacts.some(
    (artifact) => artifact.similarity_notice,
  );
  const allGreen = frameworkStatus === "pipeline_passed";

  return [
    {
      description: hasArtifacts
        ? "Every artifact must scan clean before publish."
        : "Upload at least one artifact to start scanning.",
      label: "Virus scan",
      state: allClean
        ? "pass"
        : hasInfected || hasScanError
          ? "fail"
          : hasArtifacts
            ? "pending"
            : "idle",
      value: allClean
        ? "Clean"
        : hasInfected
          ? "Infected"
          : hasArtifacts
            ? "Pending"
            : "Not started",
    },
    {
      description: anyPiiReview
        ? "Replace or resolve the flagged artifact before publishing."
        : "PII checks protect users from publishing sensitive data.",
      label: "PII review",
      state: anyPiiReview
        ? "fail"
        : allProcessed || allGreen
          ? "pass"
          : hasArtifacts
            ? "pending"
            : "idle",
      value: anyPiiReview
        ? "Review required"
        : allProcessed || allGreen
          ? "Passed"
          : hasArtifacts
            ? "Pending"
            : "Not started",
    },
    {
      description: anyNearDuplicate
        ? "This artifact appears to be a near-duplicate. Admin review is required before publishing."
        : hasSimilarityNotice
          ? "A similar published Framework was found. This notice does not block publishing."
          : "Similarity checks block only near-duplicate submissions.",
      label: "Similarity",
      state: anyNearDuplicate
        ? "fail"
        : hasSimilarityNotice
          ? "notice"
          : allProcessed || allGreen
            ? "pass"
            : hasArtifacts
              ? "pending"
              : "idle",
      value: anyNearDuplicate
        ? "Near duplicate"
        : hasSimilarityNotice
          ? "Notice"
          : allProcessed || allGreen
            ? "Passed"
            : hasArtifacts
              ? "Pending"
              : "Not started",
    },
  ];
}

/**
 * Render publish-gate checks for one Framework.
 *
 * @param props - Framework status and attached artifacts.
 */
export function PipelineStatusPanel({
  artifacts,
  frameworkId,
  frameworkStatus,
}: PipelineStatusPanelProps) {
  const checks = buildPipelineChecks(artifacts, frameworkStatus);
  const notices = artifacts.filter((artifact) => artifact.similarity_notice);
  const [differentiationNote, setDifferentiationNote] = useState("");
  const [noticeError, setNoticeError] = useState<string | null>(null);
  const [noticeSaved, setNoticeSaved] = useState(false);
  const [savingNotice, setSavingNotice] = useState(false);
  const canAcknowledge = isLengthBetween(differentiationNote, 5, 1000);

  async function handleNoticeAcknowledgement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNoticeError(null);
    setNoticeSaved(false);
    setSavingNotice(true);
    configureBrowserClient();
    const result = await acknowledgeSimilarityNotice({
      body: { differentiation_note: differentiationNote },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok || !result.data) {
      setNoticeError(describeGeneratedError(result.error));
      setSavingNotice(false);
      return;
    }
    setNoticeSaved(true);
    setSavingNotice(false);
  }

  return (
    <section className="min-w-0 rounded-2xl border border-border-default bg-surface-1 p-6 sm:p-8 shadow-sm">
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-heading text-lg font-bold text-foreground">
            Pipeline status
          </h2>
          <p className="text-sm text-foreground-muted">
            Publishing unlocks once every check below passes.
          </p>
        </div>
        <span className="w-fit rounded-xl border border-border-default px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {formatFrameworkStatus(frameworkStatus)}
        </span>
      </div>
      <div className="relative mt-2 flex flex-col pt-2">
        {checks.map((check, index) => {
          const isLast = index === checks.length - 1;
          const isPass = check.state === "pass";
          const isPending = check.state === "pending";
          const isFail = check.state === "fail";
          const isNotice = check.state === "notice";

          let nodeColor = "bg-surface-2 border-border-default text-foreground-muted";
          let icon = <span className="h-2 w-2 rounded-full bg-current" />;
          
          if (isPass) {
            nodeColor = "bg-success/10 border-success/30 text-success";
            icon = <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><polyline points="20 6 9 17 4 12"></polyline></svg>;
          } else if (isFail) {
            nodeColor = "bg-error/10 border-error/30 text-error";
            icon = <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>;
          } else if (isNotice) {
            nodeColor = "bg-info/10 border-info/30 text-info";
            icon = <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>;
          } else if (isPending) {
            nodeColor = "bg-warning/10 border-warning/30 text-warning";
            icon = <span className="h-2.5 w-2.5 animate-ping rounded-full bg-warning opacity-75" />;
          }

          const lineColor = isPass ? "bg-success/30" : "bg-border-default/60";
          const cardClass = isPass 
            ? "border-success/10 bg-success/5" 
            : isPending 
              ? "border-warning/20 bg-warning/5 ring-1 ring-warning/10" 
              : "border-border-default bg-background hover:bg-surface-2";

          return (
            <div className="relative flex gap-5 pb-8 last:pb-0" key={check.label}>
              {/* Timeline graphics */}
              <div className="relative flex flex-col items-center">
                {/* Node */}
                <div
                  className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 shadow-sm transition-colors duration-500 ${nodeColor}`}
                >
                  {isPending && (
                    <span className="absolute inline-flex h-2.5 w-2.5 rounded-full bg-warning" />
                  )}
                  {icon}
                </div>
                {/* Connecting Line */}
                {!isLast && (
                  <div
                    className={`absolute bottom-[-2rem] top-10 w-[2px] rounded-full transition-colors duration-500 ${lineColor}`}
                  />
                )}
              </div>

              {/* Content Card */}
              <div className="flex-1">
                <div
                  className={`rounded-2xl border p-5 shadow-sm transition-all duration-300 ${cardClass}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-semibold text-foreground">{check.label}</p>
                    <span className={badgeClass(check.state)}>{check.value}</span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-foreground-muted">
                    {check.description}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {notices.length > 0 ? (
        <div className="mt-5 rounded-2xl border border-info/30 bg-info/10 p-4 shadow-sm">
          <p className="text-sm font-semibold text-info">
            Similar published Framework found
          </p>
          <div className="mt-3 grid gap-3">
            {notices.map((artifact) => {
              const notice = artifact.similarity_notice;
              if (!notice) {
                return null;
              }
              const reviewText = notice.average_review_score
                ? `${notice.average_review_score} average from ${notice.review_count} review${
                    notice.review_count === 1 ? "" : "s"
                  }`
                : "No reviews yet";
              return (
                <div className="text-sm text-foreground-muted" key={artifact.id}>
                  <p>
                    {artifact.name} is similar to{" "}
                    {notice.nearest_match_title ?? "another published Framework"}.
                  </p>
                  <p className="mt-1">
                    Jaccard {notice.jaccard}. {reviewText}.
                  </p>
                </div>
              );
            })}
          </div>
          <form className="mt-4 grid gap-3" onSubmit={handleNoticeAcknowledgement}>
            <label className="grid gap-2 text-sm font-medium text-foreground">
              Differentiation note
              <textarea
                className="min-h-28 rounded-xl border border-border-default bg-background px-3 py-2 text-sm font-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
                maxLength={1000}
                minLength={5}
                onChange={(event) => setDifferentiationNote(event.target.value)}
                placeholder="Explain how this Framework differs in approach, scope, jurisdiction, or implementation detail."
                value={differentiationNote}
              />
            </label>
            {noticeError ? <p className="text-sm text-error">{noticeError}</p> : null}
            {noticeSaved ? (
              <p className="text-sm text-success">Similarity notice acknowledged.</p>
            ) : null}
            <button
              className="min-h-12 rounded-xl bg-foreground px-4 text-sm font-semibold text-background transition hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={savingNotice || !canAcknowledge}
              type="submit"
            >
              {savingNotice ? "Saving" : "Acknowledge notice"}
            </button>
          </form>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Return Brand Book semantic status badge classes.
 *
 * @param state - Pipeline check state.
 */
function badgeClass(state: PipelineCheck["state"]): string {
  if (state === "pass") {
    return "rounded-[4px] border border-success/20 bg-success/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-success";
  }
  if (state === "fail") {
    return "rounded-[4px] border border-error/20 bg-error/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-error";
  }
  if (state === "notice") {
    return "rounded-[4px] border border-info/20 bg-info/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-info";
  }
  if (state === "idle") {
    return "rounded-[4px] border border-border-default bg-surface-2 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";
  }
  return "rounded-[4px] border border-warning/20 bg-warning/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-warning";
}
