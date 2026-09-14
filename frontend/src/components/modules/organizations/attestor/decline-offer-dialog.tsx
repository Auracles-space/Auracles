"use client";

/**
 * Confirmation dialog for declining an attestation offer.
 *
 * Declining is one-way — the request goes back to matching and the offer
 * cannot be re-opened — so it is gated behind an explicit confirm step rather
 * than firing on a single click. The optional reason is stored on the offer
 * and read by admins triaging the match queue; the requestor never sees it,
 * and the copy says so.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */
import { useId, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Textarea } from "@/components/ui/textarea";
import { declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost as declineOffer } from "@/lib/generated/sdk.gen";
import {
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/** Maximum length the backend accepts for a decline reason. */
export const DECLINE_REASON_MAX_LENGTH = 500;

type DeclineOfferDialogProps = {
  /** Organization holding the offer. */
  orgId: string;
  /** Offer being declined. */
  offerId: string;
  /** Dismiss without declining. */
  onClose: () => void;
  /** Called after the decline succeeds so the caller can refresh. */
  onDone: () => void;
};

/**
 * Ask for confirmation, then decline the offer with an optional reason.
 *
 * @param props - Organization and offer ids plus close/done callbacks.
 */
export function DeclineOfferDialog({
  orgId,
  offerId,
  onClose,
  onDone,
}: DeclineOfferDialogProps) {
  const reasonId = useId();
  const helperId = `${reasonId}-helper`;
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setBusy(true);
    setError(null);
    const trimmed = reason.trim();
    const result = await declineOffer({
      // Send the reason only when there is one: an empty string would store a
      // blank reason and read to an admin as "declined, no explanation given".
      body: trimmed ? { reason: trimmed } : {},
      headers: getAccessTokenHeaders(),
      path: { offer_id: offerId, org_id: orgId },
    });
    setBusy(false);
    if (result.error) {
      setError(describeGeneratedError(result.error));
      return;
    }
    onDone();
  }

  return (
    <ConfirmDialog
      busy={busy}
      cancelLabel="Keep offer"
      confirmLabel="Decline offer"
      description={
        <div className="space-y-4">
          <p>
            The request goes back to matching and another organization may be
            offered it. You cannot take this offer back once declined.
          </p>
          <div className="flex flex-col gap-2">
            <label
              className="text-sm font-semibold text-foreground"
              htmlFor={reasonId}
            >
              Reason (optional)
            </label>
            <Textarea
              aria-describedby={helperId}
              disabled={busy}
              id={reasonId}
              maxLength={DECLINE_REASON_MAX_LENGTH}
              onChange={(event) => setReason(event.target.value)}
              value={reason}
            />
            <div className="flex items-start justify-between gap-3 text-xs text-foreground-muted">
              <p id={helperId}>Admins see this; the requestor does not.</p>
              <span aria-hidden="true" className="shrink-0 tabular-nums">
                {reason.length}/{DECLINE_REASON_MAX_LENGTH}
              </span>
            </div>
          </div>
        </div>
      }
      error={error}
      onClose={onClose}
      onConfirm={handleConfirm}
      open
      title="Decline this offer?"
      tone="danger"
    />
  );
}
