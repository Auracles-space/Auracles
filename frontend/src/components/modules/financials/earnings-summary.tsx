"use client";

/**
 * Contributor earnings summary.
 *
 * Reads refund-safe earnings from the backend financials endpoint and displays
 * only aggregate balances. Individual buyer/payment details are not exposed.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getContributorEarnings } from "@/lib/generated/sdk.gen";
import type { EarningsResponse } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

/**
 * Render Contributor gross, pending, and available payout balances.
 */
export function EarningsSummary() {
  const [earnings, setEarnings] = useState<EarningsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadEarnings() {
      configureBrowserClient();
      const result = await getContributorEarnings({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setEarnings(result.data);
      setLoading(false);
    }

    void loadEarnings();
  }, []);

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading earnings.</p>;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (!earnings) {
    return null;
  }

  const commissionPercent = `${Number(earnings.commission_rate) * 100}%`;

  return (
    <section className="grid gap-4 md:grid-cols-3">
      <article className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Available payout
        </p>
        <p className="mt-3 font-heading text-3xl font-bold text-foreground">
          {formatMoney(earnings.available_balance, earnings.currency)}
        </p>
        <p className="mt-2 text-sm text-foreground-muted">
          Minimum payout {formatMoney(earnings.minimum_payout, earnings.currency)}
        </p>
      </article>
      <article className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Gross revenue
        </p>
        <p className="mt-3 font-heading text-3xl font-bold text-foreground">
          {formatMoney(earnings.gross_revenue, earnings.currency)}
        </p>
        <p className="mt-2 text-sm text-foreground-muted">
          {commissionPercent} commission
        </p>
      </article>
      <article className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Pending clearance
        </p>
        <p className="mt-3 font-heading text-3xl font-bold text-foreground">
          {formatMoney(earnings.pending_clearance, earnings.currency)}
        </p>
        <p className="mt-2 text-sm text-foreground-muted">
          Held until the refund window closes.
        </p>
      </article>
    </section>
  );
}
