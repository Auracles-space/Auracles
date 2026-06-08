"use client";

/**
 * PII review resolution action.
 *
 * The long-term format-preserving redaction slice will expand this; for now it
 * exposes the backend re-run action after a Contributor replaces the object.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { resolveArtifactPiiReview } from "@/lib/generated/sdk.gen";
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
    router.refresh();
  }

  if (flagged.length === 0) {
    return null;
  }

  return (
    <section className="rounded-[8px] border border-error/30 bg-error/10 p-4">
      <h2 className="font-heading text-base font-bold text-error">
        PII review required
      </h2>
      <div className="mt-3 grid gap-3">
        {flagged.map((artifact) => (
          <div className="rounded-[6px] border border-error/30 bg-background p-3" key={artifact.id}>
            <p className="text-sm font-semibold text-foreground">{artifact.name}</p>
            <button
              className="mt-2 min-h-11 rounded-[6px] border border-error px-4 py-2 text-sm font-semibold text-error hover:bg-error/10"
              onClick={() => handleResolve(artifact.id)}
              type="button"
            >
              Re-run PII review
            </button>
          </div>
        ))}
      </div>
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
    </section>
  );
}
