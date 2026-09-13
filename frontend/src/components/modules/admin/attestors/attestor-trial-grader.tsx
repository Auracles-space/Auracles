"use client";

/**
 * Calibration trial grader for one attestor application.
 *
 * Shows the nominee's rubric scores beside the fixture's answer key with the
 * auto-computed agreement and suggested result, then records the admin's
 * pass/fail decision. The decision is never automatic (2026-07-15 design):
 * the suggestion is shown, the admin confirms or overrides it.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  adminDecideTrialV1AdminOrgAttestorApplicationsApplicationIdTrialDecidePost as adminDecideTrial,
  adminGetTrialGradeV1AdminOrgAttestorApplicationsApplicationIdTrialGet as adminGetTrialGrade,
} from "@/lib/generated/sdk.gen";
import type { AdminTrialGradeResponse } from "@/lib/generated/types.gen";

type AttestorTrialGraderProps = {
  applicationId: string;
  /** Called with the decision and the application status the API returned. */
  onDecided: (result: "pass" | "fail", applicationStatus: string) => void;
  onError: (message: string) => void;
};

/**
 * Whether one rubric row falls inside the answer key's tolerance.
 *
 * @param nominee - The nominee's score, if given.
 * @param expected - The key's expected score.
 * @param tolerance - Allowed distance from the expected score.
 */
function withinTolerance(
  nominee: number | null,
  expected: number,
  tolerance: number,
): boolean {
  return nominee !== null && Math.abs(nominee - expected) <= tolerance;
}

/**
 * Render the grade comparison and the pass/fail decision.
 *
 * @param props - Application id and decision callbacks.
 */
export function AttestorTrialGrader({
  applicationId,
  onDecided,
  onError,
}: AttestorTrialGraderProps) {
  const [grade, setGrade] = useState<AdminTrialGradeResponse | null>(null);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      configureBrowserClient();
      const result = await adminGetTrialGrade({
        headers: getAccessTokenHeaders(),
        path: { application_id: applicationId },
      });
      if (cancelled) {
        return;
      }
      if (!result.response.ok || !result.data) {
        onError(describeGeneratedError(result.error));
        return;
      }
      setGrade(result.data);
    }
    void load();
    return () => {
      cancelled = true;
    };
    // onError is a stable setter from the parent; re-running on it would refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId]);

  async function decide(result: "pass" | "fail") {
    setBusy(true);
    configureBrowserClient();
    try {
      const response = await adminDecideTrial({
        headers: getAccessTokenHeaders(),
        path: { application_id: applicationId },
        body: { result, feedback: feedback.trim() || undefined },
      });
      if (!response.response.ok || !response.data) {
        onError(describeGeneratedError(response.error));
        return;
      }
      onDecided(result, response.data.status);
    } catch {
      onError("The trial decision could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  if (grade === null) {
    return (
      <p className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
        Loading the trial grade…
      </p>
    );
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          Calibration trial
        </p>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-heading text-lg font-bold text-foreground">
            {grade.score_pct ? `${grade.score_pct}%` : "Pending"}
          </span>
          <span className="text-foreground-muted">agreement</span>
          {grade.auto_result ? (
            <StatusPill
              label={`Suggested: ${grade.auto_result}`}
              status={grade.auto_result === "pass" ? "passed" : "failed"}
            />
          ) : null}
        </div>
      </div>

      <ul className="mt-3 divide-y divide-border-default rounded-xl border border-border-default bg-surface-1">
        {grade.rows.map((row) => {
          const agrees = withinTolerance(row.nominee_score, row.expected_score, row.tolerance);
          return (
            <li className="grid gap-1 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto]" key={row.dimension_id}>
              <div className="min-w-0">
                <p className="font-semibold text-foreground">{row.label}</p>
                {row.nominee_comment ? (
                  <p className="mt-1 text-sm text-foreground-muted">{row.nominee_comment}</p>
                ) : null}
              </div>
              <p className="flex items-center gap-3 text-sm tabular-nums">
                <span className={agrees ? "text-success" : "text-error"}>
                  Nominee {row.nominee_score ?? "–"}
                </span>
                <span className="text-foreground-muted">
                  Key {row.expected_score} ±{row.tolerance}
                </span>
              </p>
            </li>
          );
        })}
      </ul>

      <label className="mt-3 grid gap-2 text-sm font-medium text-foreground">
        Feedback to the nominee
        <Textarea
          className="min-h-20"
          onChange={(event) => setFeedback(event.target.value)}
          placeholder="Optional. Sent with the result."
          value={feedback}
        />
      </label>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => void decide("pass")}>
          Pass trial
        </Button>
        <Button disabled={busy} onClick={() => void decide("fail")} variant="destructive">
          Fail trial
        </Button>
      </div>
    </div>
  );
}
