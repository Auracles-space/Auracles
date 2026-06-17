"use client";

/**
 * PII review resolution action.
 *
 * Shows generated redaction review actions and keeps the replacement re-run
 * path available when a Contributor uploads a clean object manually.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  acceptArtifactRedaction,
  resolveArtifactPiiReview,
} from "@/lib/generated/sdk.gen";
import type { ArtifactResponse } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type PiiReviewResolutionProps = {
  artifacts: ArtifactResponse[];
  frameworkId: string;
};

/**
 * Render PII review actions for flagged artifacts.
 *
 * @param props - Framework id and artifact list.
 */
export function PiiReviewResolution({
  artifacts,
  frameworkId,
}: PiiReviewResolutionProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const flagged = artifacts.filter((artifact) => artifact.pii_review_needed);

  async function handleAcceptRedaction(artifactId: string) {
    configureBrowserClient();
    const result = await acceptArtifactRedaction({
      headers: getAccessTokenHeaders(),
      path: { artifact_id: artifactId, framework_id: frameworkId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setError(null);
    router.refresh();
  }

  async function handleResolve(artifactId: string) {
    configureBrowserClient();
    const result = await resolveArtifactPiiReview({
      headers: getAccessTokenHeaders(),
      path: { artifact_id: artifactId, framework_id: frameworkId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setError(null);
    router.refresh();
  }

  if (flagged.length === 0) {
    return null;
  }

  return (
    <section className="min-w-0 rounded-2xl border border-error/20 bg-error/5 p-5 sm:p-6 shadow-sm">
      <div className="mb-5 flex items-center gap-2">
        <svg className="h-5 w-5 text-error" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <h2 className="font-heading text-lg font-bold text-error">
          PII review required
        </h2>
      </div>
      <div className="grid gap-4">
        {flagged.map((artifact) => (
          <div
            className="rounded-xl border border-border-default bg-background p-5 shadow-[0_2px_8px_-2px_rgba(0,0,0,0.05)] transition-all hover:shadow-[0_4px_12px_-2px_rgba(0,0,0,0.08)]"
            key={artifact.id}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1">
                <p className="text-base font-semibold text-foreground break-all">
                  {artifact.name}
                </p>
                <p className="mt-1.5 text-sm leading-relaxed text-foreground-muted">
                  {artifact.redaction_available
                    ? "A redacted copy is ready for review."
                    : "Replace the artifact, then re-run PII review."}
                </p>
              </div>
              {artifact.redaction_available ? (
                <span className="w-fit shrink-0 rounded-xl border border-info/20 bg-info/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-info">
                  Redaction ready
                </span>
              ) : null}
            </div>
            <div className="mt-5 flex flex-col gap-3 sm:flex-row xl:flex-col">
              {artifact.redaction_available ? (
                <button
                  className="inline-flex h-10 items-center justify-center rounded-xl bg-accent px-5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-accent/90"
                  onClick={() => handleAcceptRedaction(artifact.id)}
                  type="button"
                >
                  Accept redacted copy
                </button>
              ) : null}
              <button
                className="inline-flex h-10 items-center justify-center rounded-xl border border-error/30 bg-error/5 px-5 text-sm font-semibold text-error transition-colors hover:bg-error/10"
                onClick={() => handleResolve(artifact.id)}
                type="button"
              >
                Re-run PII review
              </button>
            </div>
          </div>
        ))}
      </div>
      {error ? (
        <div className="mt-4 rounded-xl bg-error/10 p-3 text-sm text-error border border-error/20 flex items-center gap-2">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      ) : null}
    </section>
  );
}
