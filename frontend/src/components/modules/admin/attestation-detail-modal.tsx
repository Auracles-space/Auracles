"use client";

/**
 * Admin detail modal for one attestation.
 *
 * Fetches the attestation plus its offer history and shows the current status,
 * key timestamps, and which org each offer went to (or was accepted by). Read
 * only — actioning a request happens from the queue rows. Portal overlay,
 * closes on Escape or backdrop click.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAdminAttestationDetail } from "@/lib/generated/sdk.gen";
import type { AdminAttestationDetailResponse } from "@/lib/generated/types.gen";
import { StatusTag } from "@/components/modules/attestation/attestation-status";

type AttestationDetailModalProps = {
  /** Attestation to show detail for. */
  attestationId: string;
  /** Close the modal. */
  onClose: () => void;
};

/** Format an ISO timestamp for display, or a dash when absent. */
function formatWhen(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "—";
}

/**
 * Render the read-only admin detail modal for one attestation.
 *
 * @param props - The attestation id and close callback.
 */
export function AttestationDetailModal({
  attestationId,
  onClose,
}: AttestationDetailModalProps) {
  const [detail, setDetail] = useState<AdminAttestationDetailResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      configureBrowserClient();
      const result = await getAdminAttestationDetail({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setDetail(result.data);
    }
    void load();
  }, [attestationId]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") {
    return null;
  }

  const attestation = detail?.attestation;

  return createPortal(
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="max-h-[85vh] w-full overflow-y-auto rounded-t-2xl border border-border-default bg-surface-1 p-6 shadow-xl sm:max-w-lg sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Attestation detail
          </h2>
          <button
            className="rounded-lg px-2 text-sm font-semibold text-foreground-muted hover:text-foreground"
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>

        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
        {!attestation && !error ? (
          <p className="mt-4 text-sm text-foreground-muted">Loading…</p>
        ) : null}

        {attestation ? (
          <div className="mt-4 grid gap-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-heading text-base font-bold text-foreground">
                  {attestation.review_type
                    ? `${attestation.review_type} review`
                    : "Attestation request"}
                </p>
                <p className="mt-1 text-xs text-foreground-muted">
                  {attestation.id} · {attestation.currency}{" "}
                  {attestation.fee_amount}
                </p>
              </div>
              <StatusTag value={attestation.status} />
            </div>

            <dl className="grid gap-2 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Created</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.created_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Accepted</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.accepted_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Completion due</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.completion_due_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Closed</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.closed_at)}
                </dd>
              </div>
            </dl>

            <div>
              <p className="text-sm font-semibold text-foreground">
                Offers ({detail?.offers.length ?? 0})
              </p>
              <div className="mt-2 grid gap-2">
                {detail && detail.offers.length > 0 ? (
                  detail.offers.map((offer, index) => (
                    <div
                      className="rounded-xl border border-border-default bg-surface-1 p-3 text-sm"
                      key={`${offer.org_id ?? "org"}-${index}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-foreground">
                          {offer.org_name ?? "Unknown org"}
                        </span>
                        <StatusTag value={offer.status} />
                      </div>
                      <p className="mt-1 text-xs text-foreground-muted">
                        Offered {formatWhen(offer.offered_at)}
                        {offer.responded_at
                          ? ` · Responded ${formatWhen(offer.responded_at)}`
                          : ` · Expires ${formatWhen(offer.expires_at)}`}
                      </p>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-foreground-muted">
                    No offers have been made yet.
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
