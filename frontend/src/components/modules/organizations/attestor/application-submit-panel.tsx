"use client";

/**
 * Final step of the attestor application: a checklist of the owner's steps
 * with shortcuts to anything unfinished, and the submit control while the
 * application is still in the owner's hands.
 */
import { Button } from "@/components/ui/button";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

import {
  OWNER_STEPS,
  isEditable,
  stepComplete,
  submissionReadiness,
  type StepId,
} from "./application-steps";

type ApplicationSubmitPanelProps = {
  /** The live application, or null before it exists. */
  application: OrgAttestorApplicationResponse | null;
  /** Server error from the last submit attempt. */
  error: string | null;
  /** Whether a submit is in flight. */
  submitting: boolean;
  /** Open an unfinished step. */
  onGoTo: (id: StepId) => void;
  /** Send the application for review. */
  onSubmit: () => void;
};

/**
 * Render the checklist and submit control.
 *
 * @param props - Application, submit state, and callbacks.
 */
export function ApplicationSubmitPanel({
  application: app,
  error,
  submitting,
  onGoTo,
  onSubmit,
}: ApplicationSubmitPanelProps) {
  const readiness = submissionReadiness(app);
  return (
    <div className="grid gap-4">
      <ul className="grid gap-2">
        {OWNER_STEPS.map((ownerStep) => {
          const done = stepComplete(app, ownerStep.id);
          return (
            <li
              className="flex flex-col gap-2 rounded-xl border border-border-default bg-surface-1 p-3 sm:flex-row sm:items-center sm:justify-between"
              key={ownerStep.id}
            >
              <span className="text-sm font-semibold text-foreground">
                {ownerStep.label}
                <span className={`ml-2 text-xs font-medium ${done ? "text-success" : "text-foreground-muted"}`}>
                  {done ? "Done" : "Not done"}
                </span>
              </span>
              {!done ? (
                <Button onClick={() => onGoTo(ownerStep.id)} variant="secondary">
                  Go to {ownerStep.label.toLowerCase()}
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {app && isEditable(app) ? (
        <div className="grid gap-2">
          <p className="text-sm text-foreground-muted">{readiness.hint}</p>
          {error ? <p className="text-sm text-error">{error}</p> : null}
          <Button
            className="w-full sm:w-auto sm:justify-self-start"
            disabled={!readiness.ready || submitting}
            loading={submitting}
            onClick={onSubmit}
          >
            {app.status === "needs_info" ? "Resubmit for review" : "Submit for review"}
          </Button>
        </div>
      ) : (
        <p className="text-sm text-foreground-muted">
          {app ? "The application has been submitted. Its progress is shown above." : readiness.hint}
        </p>
      )}
    </div>
  );
}
