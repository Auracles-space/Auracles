"use client";

/**
 * Horizontal step navigation for the attestor application.
 *
 * Earlier steps and the first unfinished one stay reachable; later steps open
 * as each step is saved. Each step shows whether it is complete. Phones get a compact "Step n of 6"
 * summary with a progress bar and rely on Back/Next; the full step row
 * appears from `sm:`.
 */
import { CheckIcon } from "@radix-ui/react-icons";

import type { ApplicationStep, StepId } from "./application-steps";

type ApplicationStepperProps = {
  /** Steps in order. */
  steps: readonly ApplicationStep[];
  /** The step whose panel is open. */
  activeId: StepId;
  /** Whether a step is complete. */
  isComplete: (id: StepId) => boolean;
  /** Whether a step can be opened yet. */
  isEnabled: (id: StepId) => boolean;
  /** Open a step. */
  onSelect: (id: StepId) => void;
};

/**
 * Render the step row and the phone summary.
 *
 * @param props - Steps, active step, completion check, and selection callback.
 */
export function ApplicationStepper({
  steps,
  activeId,
  isComplete,
  isEnabled,
  onSelect,
}: ApplicationStepperProps) {
  const activeIndex = steps.findIndex((step) => step.id === activeId);

  return (
    <nav aria-label="Application steps">
      <div className="sm:hidden">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          Step {activeIndex + 1} of {steps.length}
        </p>
        <div aria-hidden className="mt-2 flex gap-1">
          {steps.map((step, index) => (
            <span
              className={`h-1.5 flex-1 rounded-sm ${
                isComplete(step.id)
                  ? "bg-success"
                  : index === activeIndex
                    ? "bg-accent"
                    : "bg-surface-3"
              }`}
              key={step.id}
            />
          ))}
        </div>
      </div>

      <ol className="hidden gap-2 sm:grid sm:grid-cols-6">
        {steps.map((step, index) => {
          const active = step.id === activeId;
          const complete = isComplete(step.id);
          const enabled = isEnabled(step.id);
          return (
            <li key={step.id}>
              <button
                aria-current={active ? "step" : undefined}
                aria-label={`Step ${index + 1}: ${step.label}${complete ? ", complete" : ""}`}
                className={`flex min-h-11 w-full flex-col items-start gap-2 rounded-xl border px-3 py-2.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50 ${
                  // Orange marks the step in progress; an open step that is
                  // already done (e.g. Submit after approval) rings green.
                  active
                    ? complete
                      ? "border-success/50 bg-surface-2"
                      : "border-accent/50 bg-surface-2"
                    : "border-border-default bg-surface-1 enabled:hover:bg-surface-2"
                }`}
                disabled={!enabled}
                onClick={() => onSelect(step.id)}
                type="button"
              >
                <span
                  aria-hidden
                  className={`flex h-7 w-7 items-center justify-center rounded-lg border text-xs font-semibold ${
                    complete
                      ? "border-success/30 bg-success/10 text-success"
                      : active
                        ? "border-transparent bg-foreground text-background"
                        : "border-border-default text-foreground-muted"
                  }`}
                >
                  {complete ? <CheckIcon className="h-4 w-4" /> : index + 1}
                </span>
                <span
                  className={`text-xs font-semibold ${active ? "text-foreground" : "text-foreground-muted"}`}
                >
                  {step.label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
