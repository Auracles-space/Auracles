"use client";

/**
 * Requestor decision block for a submitted Attestation report.
 *
 * Accepting releases the escrow to the attestor; disputing sends it to the
 * trust team. The dispute needs a category the backend understands and enough
 * evidence for a human to act on, so both are captured here rather than the
 * previous hardcoded `scope_error` with free text.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  acceptAttestationReport,
  createAttestationDispute,
} from "@/lib/generated/sdk.gen";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  DISPUTE_CATEGORIES,
  type DisputeCategory,
} from "@/components/modules/attestation/attestation-status";
import { formatAttestationDate } from "@/components/modules/attestation/requestor-next-step";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";

/**
 * Minimum evidence length. Mirrors the backend's configured minimum so the
 * requestor is told before the request is rejected, not after.
 */
const MIN_REASON_LENGTH = 40;

type AttestationDecisionPanelProps = {
  /** Attestation under decision. */
  attestationId: string;
  /** When the dispute window closes, if the backend has set one. */
  disputeWindowEndsAt?: string | null;
  /** Called with the updated attestation after an accept. */
  onAccepted: (attestation: AttestationRequestResponse) => void;
  /** Called after a dispute is raised, to reload the request. */
  onDisputed: () => void;
};

/**
 * Render the accept-or-dispute decision block.
 *
 * @param props - Attestation id, dispute deadline, and result callbacks.
 */
export function AttestationDecisionPanel({
  attestationId,
  disputeWindowEndsAt,
  onAccepted,
  onDisputed,
}: AttestationDecisionPanelProps) {
  const [category, setCategory] = useState<DisputeCategory>(
    DISPUTE_CATEGORIES[0][0],
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deadline = formatAttestationDate(disputeWindowEndsAt);

  /** Accept the report and release escrow to the attestor. */
  async function handleAccept() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await acceptAttestationReport({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      onAccepted(result.data);
    } finally {
      setBusy(false);
    }
  }

  /** Raise a categorised dispute against the report. */
  async function handleDispute() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await createAttestationDispute({
        body: { category, reason },
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setReason("");
      onDisputed();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Decision
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Accept the report to release the fee to the attestor, or dispute it
        while the window is open.
      </p>
      {deadline ? (
        <p className="mt-2 text-sm font-semibold text-warning">
          Dispute by {deadline}
        </p>
      ) : null}

      <button
        className="mt-4 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={busy}
        onClick={handleAccept}
        type="button"
      >
        Accept report
      </button>

      <div className="mt-5 grid gap-3 rounded-xl bg-surface-2 p-4">
        <p className="text-sm font-semibold text-foreground">
          Dispute this report
        </p>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Category
          <Select
            onChange={(event) =>
              setCategory(event.target.value as DisputeCategory)
            }
            value={category}
          >
            {DISPUTE_CATEGORIES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          What went wrong
          <Textarea
            onChange={(event) => setReason(event.target.value)}
            value={reason}
          />
        </label>
        <p className="text-xs leading-5 text-foreground-muted">
          Describe what is wrong and point to the evidence (at least{" "}
          {MIN_REASON_LENGTH} characters).
        </p>
        <button
          className="min-h-12 rounded-xl border border-error/50 px-6 text-sm font-semibold text-error outline-none transition hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
          disabled={busy || reason.trim().length < MIN_REASON_LENGTH}
          onClick={handleDispute}
          type="button"
        >
          Raise dispute
        </button>
      </div>

      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
    </div>
  );
}
