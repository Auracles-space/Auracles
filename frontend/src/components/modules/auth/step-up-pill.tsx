"use client";

/**
 * Status pill showing that the user is inside a verified step-up window.
 *
 * Shown in the admin and organization shells so people working a queue can
 * see they will not be asked for a code again for the next few minutes.
 * Renders nothing when no window is open.
 */
import { LockClosedIcon } from "@radix-ui/react-icons";

import { useStepUpStatus } from "@/lib/auth/use-step-up-status";

/**
 * Render the "Verified · N min" pill while a step-up window is open.
 */
export function StepUpPill() {
  const { active, minutesLeft } = useStepUpStatus();
  if (!active) {
    return null;
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-badge border border-success/30 bg-success/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-success"
      title="Sensitive actions will not ask for a code until this window closes."
    >
      <LockClosedIcon aria-hidden="true" className="h-3 w-3" />
      Verified · {minutesLeft} min
    </span>
  );
}
