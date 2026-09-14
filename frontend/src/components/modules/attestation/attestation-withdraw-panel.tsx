"use client";

/**
 * Self-service withdrawal for an Attestation request no attestor has taken on.
 *
 * Until an organization accepts, the requestor can pull the request back and
 * get the fee refunded on its original rail. Once someone has accepted, the
 * affordance disappears and the page says why, rather than leaving a button
 * that only ever returns a 409.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { cancelAttestationRequest } from "@/lib/generated/sdk.gen";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/** Statuses a requestor may still withdraw from. */
export const WITHDRAWABLE_STATUSES = [
  "pending_owner_consent",
  "matching",
  "offered",
  "needs_admin",
];

/** Statuses that mean an attestor has taken the work on. */
export const ACCEPTED_STATUSES = [
  "accepted",
  "in_review",
  "revision_requested",
  "report_submitted",
  "disputed",
];

type AttestationWithdrawPanelProps = {
  /** Attestation to withdraw. */
  attestationId: string;
  /** Current request status. */
  status: string;
  /** Whether a fee is already held in escrow, which changes the refund copy. */
  feePaid: boolean;
  /** Called after a successful withdrawal, to reload the request. */
  onWithdrawn: () => void;
};

/**
 * Render the withdraw control, or the reason it is no longer available.
 *
 * @param props - Attestation id, status, escrow state, and reload callback.
 */
export function AttestationWithdrawPanel({
  attestationId,
  status,
  feePaid,
  onWithdrawn,
}: AttestationWithdrawPanelProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (ACCEPTED_STATUSES.includes(status)) {
    return (
      <p className="mt-4 text-sm text-foreground-muted">
        An attestor has accepted, so this request can no longer be withdrawn.
      </p>
    );
  }

  if (!WITHDRAWABLE_STATUSES.includes(status)) {
    return null;
  }

  /** Withdraw the request and refund any held fee. */
  async function handleConfirm() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await cancelAttestationRequest({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setOpen(false);
      onWithdrawn();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4">
      <button
        className="min-h-12 rounded-xl border border-error/50 px-6 text-sm font-semibold text-error outline-none transition hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
        onClick={() => setOpen(true)}
        type="button"
      >
        Withdraw request
      </button>
      <ConfirmDialog
        confirmLabel="Yes, withdraw"
        description={
          feePaid
            ? "Your request is cancelled and the fee is refunded to the original payment method."
            : "Your request is cancelled. Nothing has been charged, so there is nothing to refund."
        }
        error={error}
        busy={busy}
        onClose={() => setOpen(false)}
        onConfirm={handleConfirm}
        open={open}
        title="Withdraw this request?"
        tone="danger"
      />
    </div>
  );
}
