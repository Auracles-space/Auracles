"use client";

/**
 * PII review resolution modal.
 *
 * Presents the redaction-accept and re-run actions for PII-flagged artifacts in
 * a focus-trapped dialog opened from the pipeline status card. Actions run
 * through the seller-scoped Framework API adapter so the flow works for both
 * personal and organization Frameworks, then call `onResolved` to reload the
 * workspace — the backend stays authoritative for enforcement.
 */
import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";

import type { FrameworkApi } from "@/lib/frameworks/framework-api";
import { FrameworkApiError } from "@/lib/frameworks/framework-api";
import type { ArtifactResponse } from "@/lib/generated/types.gen";

type PiiReviewResolutionProps = {
  /** Whether the dialog is mounted and visible. */
  open: boolean;
  /** Seller-scoped Framework API adapter for the resolution actions. */
  api: FrameworkApi;
  artifacts: ArtifactResponse[];
  frameworkId: string;
  /** Dismiss the dialog. */
  onClose: () => void;
  /** Reload the workspace after a successful resolution. */
  onResolved: () => void;
};

/** Plain-language plural labels for Presidio PII entity types. */
const PII_TYPE_LABELS: Record<string, string> = {
  EMAIL_ADDRESS: "email addresses",
  PHONE_NUMBER: "phone numbers",
  PERSON: "names",
  LOCATION: "addresses or locations",
  CREDIT_CARD: "credit card numbers",
  CRYPTO: "crypto wallet addresses",
  IBAN_CODE: "bank account numbers (IBAN)",
  US_SSN: "government ID numbers",
  US_ITIN: "government ID numbers",
  US_BANK_NUMBER: "bank account numbers",
  US_PASSPORT: "passport numbers",
  US_DRIVER_LICENSE: "driver's licence numbers",
  MEDICAL_LICENSE: "medical licence numbers",
};

/**
 * Render detected PII entity types as a readable, de-duplicated phrase.
 *
 * @param types - Raw Presidio entity types from the artifact response.
 * @returns A comma list with an Oxford "and", or empty string when none.
 */
function describePiiTypes(types: string[]): string {
  const labels = Array.from(
    new Set(types.map((type) => PII_TYPE_LABELS[type] ?? type.toLowerCase())),
  );
  if (labels.length === 0) {
    return "";
  }
  if (labels.length === 1) {
    return labels[0];
  }
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

/**
 * Render PII review actions for flagged artifacts inside a dialog.
 *
 * @param props - Open state, adapter, framework context, and callbacks.
 */
export function PiiReviewResolution({
  open,
  api,
  artifacts,
  frameworkId,
  onClose,
  onResolved,
}: PiiReviewResolutionProps) {
  const titleId = useId();
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const flagged = artifacts.filter((artifact) => artifact.pii_review_needed);

  // Close on Escape so keyboard users can dismiss the dialog.
  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  async function runAction(
    artifactId: string,
    action: (id: string, artifactId: string) => Promise<ArtifactResponse>,
  ) {
    setPendingId(artifactId);
    setError(null);
    try {
      await action(frameworkId, artifactId);
    } catch (caught) {
      setError(
        caught instanceof FrameworkApiError
          ? caught.message
          : "The request could not be completed.",
      );
      return;
    } finally {
      setPendingId(null);
    }
    onResolved();
  }

  if (!open || flagged.length === 0 || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      aria-labelledby={titleId}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 motion-safe:animate-[fade-in_120ms_ease-out] sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl border border-border-default bg-surface-1 p-5 shadow-xl sm:max-w-lg sm:rounded-2xl sm:p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <svg
              className="h-5 w-5 text-error"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <h2
              className="font-heading text-lg font-bold text-foreground"
              id={titleId}
            >
              PII review required
            </h2>
          </div>
          <button
            aria-label="Close"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-foreground-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            onClick={onClose}
            type="button"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>
        <div className="grid gap-4">
          {flagged.map((artifact) => (
            <div
              className="rounded-xl border border-border-default bg-background p-4"
              key={artifact.id}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-base font-semibold text-foreground break-all">
                    {artifact.name}
                  </p>
                  <p className="mt-1.5 text-sm leading-relaxed text-foreground-muted">
                    {artifact.redaction_available
                      ? "A redacted copy is ready for review."
                      : artifact.redaction_status === "failed"
                        ? "We couldn't automatically redact this file (common with scanned or image-based files). Remove the personal data and upload a clean version, then re-run review."
                        : "Remove the personal data and upload a clean version, then re-run review."}
                  </p>
                  {artifact.pii_types_found &&
                  artifact.pii_types_found.length > 0 ? (
                    <p className="mt-2 text-sm leading-relaxed text-foreground">
                      <span className="font-semibold">We found:</span>{" "}
                      {describePiiTypes(artifact.pii_types_found)}.
                    </p>
                  ) : null}
                </div>
                {artifact.redaction_available ? (
                  <span className="w-fit shrink-0 rounded-xl border border-info/20 bg-info/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-info">
                    Redaction ready
                  </span>
                ) : null}
              </div>
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                {artifact.redaction_available ? (
                  <button
                    className="inline-flex min-h-11 items-center justify-center rounded-xl bg-accent px-5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-accent/90 disabled:opacity-60"
                    disabled={pendingId === artifact.id}
                    onClick={() => runAction(artifact.id, api.acceptRedaction)}
                    type="button"
                  >
                    {pendingId === artifact.id ? "Working…" : "Accept redacted copy"}
                  </button>
                ) : null}
                <button
                  className="inline-flex min-h-11 items-center justify-center rounded-xl border border-error/30 bg-error/5 px-5 text-sm font-semibold text-error transition-colors hover:bg-error/10 disabled:opacity-60"
                  disabled={pendingId === artifact.id}
                  onClick={() => runAction(artifact.id, api.resolvePiiReview)}
                  type="button"
                >
                  {pendingId === artifact.id ? "Working…" : "Re-run PII review"}
                </button>
              </div>
            </div>
          ))}
        </div>
        {error ? (
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-error/20 bg-error/10 p-3 text-sm text-error">
            <svg
              className="h-4 w-4 shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            {error}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
