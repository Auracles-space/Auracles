"use client";

/**
 * Content-use acknowledgment gate for an accepted attestation.
 *
 * The backend refuses to start a review until the reviewing member has
 * recorded the content-use acknowledgment, so the checkbox and the two calls
 * live together here and the workspace only has to know whether the review has
 * started.
 *
 * Maps to: FR-ATT review workspace.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  ackAttestationContent,
  startAttestationReview,
} from "@/lib/generated/sdk.gen";
import {
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/** Version label recorded with the reviewing member's content-use acknowledgment. */
const CONTENT_ACK_VERSION = "1.0";

type StartReviewCardProps = {
  /** Attestation being started. */
  attestationId: string;
  /** Called once the review has started so the workspace can reload. */
  onStarted: () => void | Promise<void>;
  /** Surface a failure on the workspace header. */
  onError: (message: string) => void;
};

/**
 * Render the acknowledgment checkbox and the start-review action.
 *
 * @param props - Attestation id plus started/error callbacks.
 */
export function StartReviewCard({
  attestationId,
  onStarted,
  onError,
}: StartReviewCardProps) {
  const [ackChecked, setAckChecked] = useState(false);
  const [starting, setStarting] = useState(false);

  async function handleStartReview() {
    setStarting(true);
    try {
      // Record the binding content-use acknowledgment first — the backend
      // requires it before a review can start. Idempotent if already recorded.
      const ack = await ackAttestationContent({
        path: { attestation_id: attestationId },
        body: { content_ack: true, ack_version: CONTENT_ACK_VERSION },
        headers: getAccessTokenHeaders(),
      });
      if (ack.error) throw new Error(describeGeneratedError(ack.error));

      const res = await startAttestationReview({
        path: { attestation_id: attestationId },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) throw new Error(describeGeneratedError(res.error));
      await onStarted();
    } catch (err: unknown) {
      onError(err instanceof Error ? err.message : "Failed to start review.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h3 className="font-heading text-lg font-bold text-foreground">
        Begin review
      </h3>
      <p className="mt-1 text-sm text-foreground-muted">
        Before opening the framework content, confirm the content-use terms.
        Starting the review unlocks the full artifacts and the rubric,
        annotations, clarifications, and report tools.
      </p>
      <label className="mt-4 flex items-start gap-3 py-3 text-sm text-foreground">
        <input
          checked={ackChecked}
          className="mt-0.5 h-4 w-4"
          onChange={(event) => setAckChecked(event.target.checked)}
          type="checkbox"
        />
        <span>
          I acknowledge the content-use terms and will keep this framework&apos;s
          content confidential, using it solely to perform this attestation.
        </span>
      </label>
      <Button
        className="mt-4 w-full sm:w-auto"
        disabled={!ackChecked || starting}
        loading={starting}
        onClick={handleStartReview}
      >
        Start review
      </Button>
    </section>
  );
}
