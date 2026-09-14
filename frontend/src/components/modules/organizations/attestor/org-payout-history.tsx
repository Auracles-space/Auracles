"use client";

/**
 * Organization payout history.
 *
 * Lists the org's payouts newest first (the API orders them), each with its
 * net amount in the payout's own currency, the canonical status pill, request
 * and completion dates, and the failure reason on failed payouts. Pages
 * through history with "Load more" instead of fetching everything up front.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice C.
 */
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listOrgPayoutsV1OrgsOrgIdFinancialsPayoutsGet as listOrgPayouts } from "@/lib/generated/sdk.gen";
import type { OrgPayoutHistoryItem } from "@/lib/generated/types.gen";
import { formatMoney, formatShortDate } from "@/lib/marketplace/format";
import { StatusPill } from "@/components/ui/status-pill";

const PAGE_SIZE = 20;

type OrgPayoutHistoryProps = {
  /** Organization whose payouts are listed. */
  orgId: string;
};

/**
 * Render the paginated payout history for one organization.
 *
 * @param props.orgId - Organization whose payouts are listed.
 */
export function OrgPayoutHistory({ orgId }: OrgPayoutHistoryProps) {
  const [payouts, setPayouts] = useState<OrgPayoutHistoryItem[]>([]);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPage = useCallback(
    async (nextPage: number) => {
      setLoading(true);
      setError(null);
      try {
        configureBrowserClient();
        const result = await listOrgPayouts({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
          query: { page: nextPage, page_size: PAGE_SIZE },
        });
        if (!result.data) {
          setError(describeGeneratedError(result.error));
          return;
        }
        const data = result.data;
        setPayouts((current) => (nextPage === 1 ? data.payouts : [...current, ...data.payouts]));
        setPage(data.page);
        setTotal(data.total);
      } catch (caught) {
        setError(describeGeneratedError(caught));
      } finally {
        setLoading(false);
      }
    },
    [orgId],
  );

  useEffect(() => {
    void loadPage(1);
  }, [loadPage]);

  const hasMore = payouts.length < total;

  return (
    <section>
      <h3 className="mb-4 text-lg font-medium">Payouts</h3>
      {error ? (
        <p className="mb-4 rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && !error && payouts.length === 0 ? (
        <p className="text-sm text-foreground-subtle">No payouts yet.</p>
      ) : null}
      {payouts.length > 0 ? (
        <ul className="grid gap-3">
          {payouts.map((payout) => (
            <PayoutRow key={payout.id} payout={payout} />
          ))}
        </ul>
      ) : null}
      {hasMore ? (
        <button
          className="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-control border border-border-strong bg-surface-1 px-4 text-sm font-semibold text-foreground outline-none transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
          disabled={loading}
          onClick={() => void loadPage(page + 1)}
          type="button"
        >
          Load more
        </button>
      ) : null}
    </section>
  );
}

/** Render one payout as a card on phones and a wrapping row on wider screens. */
function PayoutRow({ payout }: { payout: OrgPayoutHistoryItem }) {
  return (
    <li className="grid gap-2 rounded-lg border border-border-strong bg-surface-2 p-4 sm:flex sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6">
      <div className="flex flex-wrap items-center gap-3">
        <p className="font-bold tabular-nums">{formatMoney(payout.amount, payout.currency)}</p>
        <StatusPill status={payout.status} />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-foreground-subtle">
        <span>Requested {formatShortDate(payout.requested_at)}</span>
        {payout.completed_at ? <span>Paid {formatShortDate(payout.completed_at)}</span> : null}
      </div>
      {payout.status === "failed" && payout.failure_reason ? (
        <p className="text-sm text-error sm:basis-full">{payout.failure_reason}</p>
      ) : null}
    </li>
  );
}
