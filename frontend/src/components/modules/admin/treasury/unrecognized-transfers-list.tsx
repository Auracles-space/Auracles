"use client";

/**
 * Transfers out of the platform balance that Auracles did not start.
 *
 * Each one is money that left through the provider dashboard or another route
 * outside the product. Every admin sees them; only the super-admin marks one
 * reviewed after investigating, which is audited.
 *
 * Maps to: platform treasury design, decision 5.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { formatTimestamp, Pill } from "@/components/modules/admin/admin-money-primitives";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { adminAcknowledgeUnrecognizedTransferV1AdminTreasuryUnrecognizedTransfersTransferIdAcknowledgePost as acknowledgeTransfer } from "@/lib/generated/sdk.gen";
import type { UnrecognizedTransferItem } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

/**
 * Render the unrecognized transfer list, or nothing when there are none.
 *
 * @param transfers - Transfers, unreviewed first.
 * @param canAcknowledge - Whether the viewer is the super-admin.
 * @param onAcknowledged - Called after one was marked reviewed.
 */
export function UnrecognizedTransfersList({
  transfers,
  canAcknowledge,
  onAcknowledged,
}: {
  transfers: UnrecognizedTransferItem[];
  canAcknowledge: boolean;
  onAcknowledged: () => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (transfers.length === 0) {
    return null;
  }

  async function acknowledge(transferId: string) {
    setBusyId(transferId);
    setError(null);
    configureBrowserClient();
    const result = await acknowledgeTransfer({
      headers: getAccessTokenHeaders(),
      path: { transfer_id: transferId },
    });
    setBusyId(null);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    onAcknowledged();
  }

  return (
    <section className="rounded-2xl border border-error/30 bg-surface-1 p-5 shadow-sm">
      <h3 className="font-heading text-lg font-bold text-foreground">
        Transfers not started by Auracles
      </h3>
      <p className="mt-1 text-sm text-foreground-muted">
        Money that left the Paystack balance without a matching payout or withdrawal.
      </p>
      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
      <ul className="mt-4 grid gap-3">
        {transfers.map((transfer) => (
          <li
            className="grid gap-2 rounded-xl border border-border-default bg-surface-2 p-4 text-sm sm:grid-cols-[1fr_auto] sm:items-center"
            key={transfer.id}
          >
            <div className="grid gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold tabular-nums">
                  {transfer.amount && transfer.currency
                    ? formatMoney(transfer.amount, transfer.currency)
                    : "Amount not reported"}
                </span>
                <Pill tone={transfer.acknowledged_at ? "default" : "error"}>
                  {transfer.acknowledged_at ? "Reviewed" : "Needs review"}
                </Pill>
              </div>
              <span className="text-foreground-muted">
                {transfer.recipient_name ?? "Unknown recipient"}
                {transfer.recipient_last4
                  ? ` · ${transfer.recipient_bank ?? "Bank"} ****${transfer.recipient_last4}`
                  : ""}
              </span>
              <span className="text-xs text-foreground-muted">
                {formatTimestamp(transfer.created_at)} · {transfer.event_type} ·{" "}
                <span className="font-mono">{transfer.reference}</span>
              </span>
            </div>
            {canAcknowledge && !transfer.acknowledged_at ? (
              <Button
                loading={busyId === transfer.id}
                onClick={() => void acknowledge(transfer.id)}
                variant="secondary"
              >
                Mark reviewed
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
