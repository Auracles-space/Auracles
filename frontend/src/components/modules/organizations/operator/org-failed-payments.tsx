"use client";

/**
 * Organization failed payments.
 *
 * Lists Framework purchases whose payment failed, with the framework title,
 * amount in the purchase's own currency, date, and the provider's failure
 * reason, so an org admin can fix the payment method and retry. Renders
 * nothing when no purchase has failed.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice C.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listOrgPurchasesV1OrgsOrgIdFinancialsPurchasesGet as listOrgPurchases } from "@/lib/generated/sdk.gen";
import type { OrgPurchaseListItem } from "@/lib/generated/types.gen";
import { formatMoney, formatShortDate } from "@/lib/marketplace/format";

type OrgFailedPaymentsProps = {
  /** Organization whose failed purchases are listed. */
  orgId: string;
};

/**
 * Render the failed payments card, or nothing when there are none.
 *
 * @param props.orgId - Organization whose failed purchases are listed.
 */
export function OrgFailedPayments({ orgId }: OrgFailedPaymentsProps) {
  const [purchases, setPurchases] = useState<OrgPurchaseListItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        configureBrowserClient();
        const result = await listOrgPurchases({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
          query: { status: "failed" },
        });
        if (!result.data) {
          setError(describeGeneratedError(result.error));
          return;
        }
        setError(null);
        setPurchases(result.data.purchases);
      } catch (caught) {
        setError(describeGeneratedError(caught));
      }
    }

    void load();
  }, [orgId]);

  if (!error && purchases.length === 0) return null;

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
      <h2 className="font-heading text-xl font-bold text-foreground">Failed payments</h2>
      {error ? (
        <p className="mt-4 text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}
      <ul className="mt-5 grid gap-3">
        {purchases.map((purchase) => (
          <li
            className="grid gap-2 rounded-xl border border-error/30 bg-error/5 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
            key={purchase.transaction_id}
          >
            <div className="min-w-0">
              <p className="break-words text-sm font-semibold text-foreground">
                {purchase.framework_title ?? "Framework no longer available"}
              </p>
              <p className="text-xs text-foreground-muted">{formatShortDate(purchase.created_at)}</p>
            </div>
            <p className="text-sm font-semibold tabular-nums text-foreground sm:text-right">
              {formatMoney(purchase.amount, purchase.currency)}
            </p>
            {purchase.failure_reason ? (
              <p className="text-sm text-error sm:col-span-2">{purchase.failure_reason}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
