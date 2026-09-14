"use client";

/**
 * Financials tab of the admin organization detail page: balances, payout
 * and purchase summaries, recent payouts and recent transactions. Every
 * amount is formatted in the currency the API returns beside it, never the
 * platform default.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useCallback } from "react";

import { EmptyNote, Fact, ListRow, PanelError, PanelSkeleton, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { StatusPill } from "@/components/ui/status-pill";
import { adminOrgFinancialsV1AdminOrgsOrgIdFinancialsGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgFinancialsResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney, formatShortDate } from "@/lib/marketplace/format";

/**
 * Render the financials tab.
 *
 * @param orgId - Organization whose money to summarise.
 */
export function OrgFinancialsTab({ orgId }: { orgId: string }) {
  const load = useCallback(
    (headers: Record<string, string>) =>
      adminOrgFinancialsV1AdminOrgsOrgIdFinancialsGet({ headers, path: { org_id: orgId } }),
    [orgId],
  );
  const { data, error, loading, retry } = useAdminOrgResource<AdminOrgFinancialsResponse>(load);

  if (loading) return <PanelSkeleton />;
  if (error || !data) return <PanelError message={error ?? "Could not load financials."} onRetry={retry} />;

  const { currency, payouts_summary: payouts, purchases_summary: purchases } = data;
  return (
    <div className="grid gap-4">
      <Section title="Summary">
        <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <Fact label="Available balance">{formatMoney(data.available_balance, currency)}</Fact>
          <Fact label="Pending balance">{formatMoney(data.pending_balance, currency)}</Fact>
          <Fact label="Paid out">{formatMoney(payouts.completed_total, currency)}</Fact>
          <Fact label="Pending payouts">{String(payouts.pending_count)}</Fact>
          <Fact label="Last payout">{formatShortDate(payouts.last_payout_at, "Never")}</Fact>
          <Fact label="Purchases">
            {formatMoney(purchases.total_spent, currency)} across {purchases.completed_count} completed,{" "}
            {purchases.failed_count} failed
          </Fact>
        </dl>
      </Section>
      <Section title="Recent payouts">
        {data.recent_payouts.length === 0 ? (
          <EmptyNote>No payouts yet.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {data.recent_payouts.map((payout) => (
              <ListRow columns="md:grid-cols-[1fr_auto_1fr_1fr]" key={payout.payout_id}>
                <p className="font-semibold text-foreground">{formatMoney(payout.amount, payout.currency)}</p>
                <StatusPill className="w-fit" status={payout.status} />
                <p className="text-sm text-foreground-muted">{payout.provider ? formatLabel(payout.provider) : "No provider"}</p>
                <p className="text-sm text-foreground-muted">
                  {formatShortDate(payout.completed_at ?? payout.initiated_at)}
                </p>
              </ListRow>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Recent transactions">
        {data.recent_transactions.length === 0 ? (
          <EmptyNote>No transactions yet.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {data.recent_transactions.map((tx) => (
              <ListRow columns="md:grid-cols-[1fr_1fr_auto_1fr]" key={tx.transaction_id}>
                <p className="font-semibold text-foreground">{formatMoney(tx.amount, tx.currency)}</p>
                <p className="text-sm text-foreground">{formatLabel(tx.transaction_type)}</p>
                <StatusPill className="w-fit" status={tx.status} />
                <p className="text-sm text-foreground-muted">{formatShortDate(tx.created_at)}</p>
              </ListRow>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
