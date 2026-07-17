"use client";

/**
 * Requestor-facing rubric scorecard for a submitted attestation report.
 *
 * Fetches the attestor's per-dimension scores and comments so the requestor can
 * see the reasoning behind the outcome before accepting or disputing. The
 * endpoint is requestor-gated server-side, so a caller without access simply
 * gets nothing to render.
 */

import { useEffect, useState } from "react";

import { getReportRubric } from "@/lib/generated/sdk.gen";
import type { RequestorRubricItem } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Spinner } from "@/components/ui/spinner";

export interface ReportRubricPanelProps {
  /** Attestation whose submitted report rubric is shown. */
  attestationId: string;
}

/**
 * Render the attestor's rubric scorecard for the report's requestor.
 *
 * @param attestationId - Attestation whose rubric is fetched.
 */
export function ReportRubricPanel({ attestationId }: ReportRubricPanelProps) {
  const [scores, setScores] = useState<RequestorRubricItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await getReportRubric({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders(),
        });
        if (!active || res.error || !res.data) return;
        setScores(res.data.scores);
      } catch {
        // Non-fatal: the scorecard is supplementary to the report body.
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [attestationId]);

  if (loading) {
    return (
      <div className="mt-4 flex items-center gap-2 text-sm text-foreground-muted">
        <Spinner className="h-4 w-4" /> Loading scorecard…
      </div>
    );
  }

  if (scores.length === 0) {
    return null;
  }

  return (
    <div className="mt-6">
      <p className="text-sm font-semibold text-foreground">Rubric scorecard</p>
      <ul className="mt-2 grid gap-3">
        {scores.map((item) => (
          <li
            key={item.dimension_key}
            className="rounded-xl border border-border-default bg-surface-2 p-4"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-semibold text-foreground">
                {item.label}
              </span>
              <span className="text-sm font-semibold text-foreground-muted">
                {item.score === null ? "—" : `${item.score} / 5`}
              </span>
            </div>
            {item.comment ? (
              <p className="mt-2 whitespace-pre-wrap text-sm text-foreground-muted">
                {item.comment}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
