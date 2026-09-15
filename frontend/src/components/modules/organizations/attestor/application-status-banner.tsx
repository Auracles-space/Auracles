"use client";

/**
 * Review-stage banner pinned above the attestor application steps.
 *
 * States where the application stands (draft, in review, trial, approval,
 * active, suspended) and what happens next, with admin or trial feedback and
 * a four-stage track, so admin-driven stages never read as owner steps.
 */
import type { ReactNode } from "react";

import { StatusPill, describeStatus } from "@/components/ui/status-pill";

import { REVIEW_TRACK, type ReviewStage } from "./application-steps";

type ApplicationStatusBannerProps = {
  /** The current stage. */
  stage: ReviewStage;
  /** Index into the review track; null hides the track. */
  trackIndex: number | null;
  /** The org's attestor capability status, for the suspension reason. */
  capability?: string;
  /** Admin's reason for a suspension or revocation. */
  capabilityReason?: string | null;
  /** Stage-specific controls, e.g. starting a new application. */
  children?: ReactNode;
};

/**
 * Render the stage banner.
 *
 * @param props - Stage, track position, capability reason, and extra controls.
 */
export function ApplicationStatusBanner({
  stage,
  trackIndex,
  capability,
  capabilityReason,
  children,
}: ApplicationStatusBannerProps) {
  const tone = describeStatus(stage.status).tone;
  const feedbackClasses =
    tone === "error"
      ? "border-error/30 bg-error/10 text-error"
      : tone === "success"
        ? "border-success/30 bg-success/10 text-success"
        : "border-warning/30 bg-warning/10 text-warning";

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Application status
          </p>
          <h3 className="mt-1 font-heading text-lg font-bold text-foreground">{stage.title}</h3>
        </div>
        <StatusPill label={stage.label} status={stage.status} />
      </div>
      <p className="mt-2 max-w-2xl text-sm text-foreground-muted">{stage.detail}</p>

      {stage.feedback ? (
        <div className={`mt-4 rounded-xl border p-3 text-sm ${feedbackClasses}`}>
          <span className="mb-1 block font-semibold">Feedback from the administrator</span>
          {stage.feedback}
        </div>
      ) : null}

      {capability === "suspended" || capability === "revoked" ? (
        <div className="mt-4 space-y-1 text-sm text-foreground">
          <p>
            <span className="font-semibold">Reason:</span>{" "}
            {capabilityReason ?? "No reason was recorded."}
          </p>
          {capability === "revoked" ? (
            <p className="text-foreground-muted">Contact support to appeal.</p>
          ) : null}
        </div>
      ) : null}

      {trackIndex !== null ? (
        <ol className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {REVIEW_TRACK.map((label, index) => (
            <li
              aria-current={index === trackIndex ? "step" : undefined}
              className={`rounded-xl border px-3 py-2 text-xs ${
                index < trackIndex
                  ? "border-success/30 bg-success/10 text-success"
                  : index === trackIndex
                    ? "border-accent/50 bg-surface-2 font-semibold text-foreground"
                    : "border-border-default text-foreground-muted"
              }`}
              key={label}
            >
              <span aria-hidden>{index + 1} · </span>
              {label}
            </li>
          ))}
        </ol>
      ) : null}

      {children ? <div className="mt-4">{children}</div> : null}
    </section>
  );
}
