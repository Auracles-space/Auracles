/**
 * Nominee calibration-trial workspace.
 *
 * Loads the nominated member's assigned trial, lets them score each rubric
 * dimension, and switches to read-only status views once submitted or decided.
 */
"use client";

import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getAttestorTrialV1OrgsOrgIdAttestorTrialGet as getAttestorTrial,
  submitAttestorTrialV1OrgsOrgIdAttestorTrialSubmitPost as submitAttestorTrial,
} from "@/lib/generated/sdk.gen";
import type {
  NomineeTrialResponse,
  TrialScoreInput,
} from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";

type TrialWorkspaceProps = {
  orgId: string;
};

type ScoreDraft = {
  score: string;
  comment: string;
};

const EMPTY_DRAFT: ScoreDraft = {
  score: "",
  comment: "",
};

function buildDrafts(savedScores: TrialScoreInput[]): Record<string, ScoreDraft> {
  return savedScores.reduce<Record<string, ScoreDraft>>((acc, item) => {
    acc[item.dimension_id] = {
      score: String(item.score),
      comment: item.comment ?? "",
    };
    return acc;
  }, {});
}

/**
 * Render the member-scoped calibration-trial workspace.
 *
 * @param orgId - Organization whose nominee trial should be loaded.
 */
export function TrialWorkspace({ orgId }: TrialWorkspaceProps) {
  const [trial, setTrial] = useState<NomineeTrialResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ScoreDraft>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      configureBrowserClient();
      try {
        const result = await getAttestorTrial({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
        });
        if (cancelled) {
          return;
        }
        if (!result.response.ok || !result.data) {
          if (result.response.status === 404) {
            const code = (result.error as { detail?: { error_code?: string } } | undefined)
              ?.detail?.error_code;
            setError(
              code === "trial_not_started"
                ? "You're nominated for your organization's calibration trial. It opens here once the attestor application is submitted and an administrator starts the trial. You'll be notified when it's ready."
                : "No calibration trial is assigned to you. If your organization nominates you, the trial appears here once an administrator starts it.",
            );
          } else if (result.response.status === 403) {
            setError("This trial is assigned to another member.");
          } else {
            setError(describeGeneratedError(result.error));
          }
          setTrial(null);
          return;
        }
        setTrial(result.data);
        setDrafts(buildDrafts(result.data.saved_scores));
      } catch {
        if (!cancelled) {
          setError("Failed to load trial.");
          setTrial(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  function updateDraft(
    dimensionId: string,
    patch: Partial<ScoreDraft>,
  ) {
    setDrafts((current) => ({
      ...current,
      [dimensionId]: {
        ...(current[dimensionId] ?? EMPTY_DRAFT),
        ...patch,
      },
    }));
  }

  async function handleSubmit() {
    if (!trial) {
      return;
    }
    setSubmitting(true);
    setError(null);
    configureBrowserClient();
    try {
      const scores = trial.dimensions.map((dimension) => ({
        dimension_id: dimension.dimension_id,
        score: Number(drafts[dimension.dimension_id]?.score ?? 0),
        comment: drafts[dimension.dimension_id]?.comment || undefined,
      }));
      const result = await submitAttestorTrial({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        body: { scores },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setTrial(result.data);
      setDrafts(buildDrafts(result.data.saved_scores));
    } catch {
      setError("Failed to submit trial.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-sm text-foreground-muted">Loading trial…</p>
      </section>
    );
  }

  if (error && !trial) {
    return (
      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-sm text-foreground">{error}</p>
      </section>
    );
  }

  if (!trial) {
    // Every load failure sets an error above, so reaching here means the call
    // resolved without a trial. Rendering nothing put a blank page on a tab
    // offered to every member — the shell documents this as a friendly
    // "no active trial" state, so say that rather than showing a white screen.
    return (
      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-sm text-foreground-muted">
          No calibration trial is assigned to you right now. If your
          organization has nominated you, the trial appears here once its
          attestor application has been reviewed.
        </p>
      </section>
    );
  }

  const allDimensionsScored = trial.dimensions.every((dimension) =>
    Boolean(drafts[dimension.dimension_id]?.score),
  );
  const isAssigned = trial.status === "assigned";
  const isSubmitted = trial.status === "submitted";
  const isPassed = trial.status === "passed";
  const isFailed = trial.status === "failed";

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Calibration Trial
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          {trial.framework_name}
        </h1>
        {trial.framework_summary ? (
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            {trial.framework_summary}
          </p>
        ) : null}
      </div>

      {error ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </p>
      ) : null}

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          Fixture Artifacts
        </h2>
        <div className="mt-4 grid gap-3">
          {trial.artifacts.length === 0 ? (
            <p className="text-sm text-foreground-muted">No artifacts attached.</p>
          ) : (
            trial.artifacts.map((artifact) => (
              <a
                key={artifact.url}
                className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-border-default px-4 py-3 text-sm text-foreground transition-colors hover:bg-surface-2"
                href={artifact.url}
                rel="noreferrer noopener"
                target="_blank"
              >
                <span>{artifact.name}</span>
                <span className="text-xs uppercase tracking-[0.05em] text-foreground-muted">
                  {artifact.mime_type}
                </span>
              </a>
            ))
          )}
        </div>
      </div>

      {(isSubmitted || isPassed || isFailed) ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-foreground">Trial outcome</h2>
            {/* Waiting on an admin is "In review" everywhere in the product. */}
            <StatusPill status={isSubmitted ? "in_review" : trial.status} />
          </div>
          <p className="mt-2 text-sm text-foreground-muted">
            {isSubmitted
              ? "Your calibration review has been submitted and is awaiting admin confirmation."
              : trial.feedback || "An admin has recorded the final trial outcome."}
          </p>
        </div>
      ) : null}

      {isAssigned ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <div className="grid gap-6">
            {trial.dimensions.map((dimension) => {
              const draft = drafts[dimension.dimension_id] ?? EMPTY_DRAFT;
              return (
                <div
                  key={dimension.dimension_id}
                  className="grid gap-3 rounded-2xl border border-border-default p-4"
                >
                  <div>
                    <p className="text-base font-semibold text-foreground">
                      {dimension.label}
                    </p>
                    <p className="text-xs uppercase tracking-[0.05em] text-foreground-muted">
                      {dimension.key}
                    </p>
                  </div>

                  <label
                    className="grid gap-2 text-sm font-medium text-foreground"
                    htmlFor={`score-${dimension.dimension_id}`}
                  >
                    <span>
                      {dimension.label} score
                      <span className="text-error" aria-hidden="true">
                        {" "}
                        *
                      </span>
                      <span className="sr-only"> (required)</span>
                    </span>
                    <select
                      id={`score-${dimension.dimension_id}`}
                      className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus:border-accent"
                      onChange={(event) =>
                        updateDraft(dimension.dimension_id, {
                          score: event.target.value,
                        })
                      }
                      value={draft.score}
                    >
                      <option value="">Select a score</option>
                      <option value="1">1</option>
                      <option value="2">2</option>
                      <option value="3">3</option>
                      <option value="4">4</option>
                      <option value="5">5</option>
                    </select>
                  </label>

                  <label
                    className="grid gap-2 text-sm font-medium text-foreground"
                    htmlFor={`comment-${dimension.dimension_id}`}
                  >
                    {dimension.label} comment{" "}
                    <span className="text-foreground-muted">(optional)</span>
                    <textarea
                      id={`comment-${dimension.dimension_id}`}
                      className="min-h-28 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus:border-accent"
                      onChange={(event) =>
                        updateDraft(dimension.dimension_id, {
                          comment: event.target.value,
                        })
                      }
                      value={draft.comment}
                    />
                  </label>
                </div>
              );
            })}
          </div>

          <div className="mt-6 flex justify-end">
            <Button
              disabled={!allDimensionsScored}
              loading={submitting}
              onClick={() => void handleSubmit()}
            >
              Submit Trial
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
