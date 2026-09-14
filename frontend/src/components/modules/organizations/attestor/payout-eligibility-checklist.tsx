/**
 * Organization payout eligibility checklist.
 *
 * Renders the unmet conditions the org earnings response reports before a
 * payout can be requested, each with a link to the surface that clears it when
 * one exists. Hidden entirely once the organization is eligible, so it never
 * competes with the payout controls.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice C.
 */
import Link from "next/link";

import type { PayoutEligibility } from "@/lib/generated/types.gen";

type PayoutEligibilityChecklistProps = {
  /** Eligibility verdict and reasons from the org earnings response. */
  eligibility: PayoutEligibility;
};

/**
 * Render the "Before you can request a payout" card, or nothing when eligible.
 *
 * @param props.eligibility - Eligibility verdict and reasons from the API.
 */
export function PayoutEligibilityChecklist({ eligibility }: PayoutEligibilityChecklistProps) {
  if (eligibility.eligible) return null;

  return (
    <section className="rounded-xl border border-warning/30 bg-warning/10 p-4 md:p-5">
      <h4 className="font-heading text-base font-bold text-foreground">
        Before you can request a payout
      </h4>
      <ul className="mt-3 grid gap-3">
        {eligibility.reasons.map((reason) => (
          <li
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-warning/20 pt-3 text-sm text-foreground first:border-t-0 first:pt-0"
            key={reason.code}
          >
            <span className="min-w-0">{reason.message}</span>
            {reason.action_path ? (
              <Link
                className="inline-flex min-h-11 items-center text-sm font-semibold text-accent underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
                href={reason.action_path}
              >
                Resolve
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
