"use client";

/**
 * Admin payouts oversight panel.
 *
 * Read-only financial oversight: administrators list and filter payouts by
 * status, provider, and organization to investigate failures and reconcile
 * transfers. Beneficiaries are named; organizations link to their admin
 * detail page. Payout destination account details are never returned by the
 * API, so nothing sensitive renders here. Every amount is formatted in its own
 * row's currency (naira on the NGN rail) via the shared `formatMoney`. Styled
 * as a responsive directory that reads as a table on desktop and stacked cards
 * on mobile.
 *
 * Maps to: admin financial oversight (payout directory).
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listAdminPayoutsV1AdminPayoutsGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { formatMoney } from "@/lib/marketplace/format";
import type {
  AdminPayoutDirectoryResponse,
  AdminPayoutItem,
} from "@/lib/generated/types.gen";

import { OrgIdFilter, OrgLink, isUuid, shortId } from "./admin-org-party";

type PayoutStatusFilter = "all" | "pending" | "processing" | "completed" | "failed";
type PayoutProviderFilter = "all" | "stripe" | "paystack";

/** Status pill styles keyed by payout status. */
const STATUS_STYLES: Record<AdminPayoutItem["status"], string> = {
  pending: "border-border-default bg-surface-2 text-foreground-muted",
  processing: "border-warning/30 bg-warning/10 text-warning",
  completed: "border-success/30 bg-success/10 text-success",
  failed: "border-error/30 bg-error/10 text-error",
};

/**
 * Format a payout timestamp for compact admin copy.
 *
 * @param value - ISO timestamp string.
 */
function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Render the read-only admin payout directory with status/provider/org filters.
 */
export function AdminPayoutsPanel() {
  const [directory, setDirectory] = useState<AdminPayoutDirectoryResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<PayoutStatusFilter>("all");
  const [providerFilter, setProviderFilter] = useState<PayoutProviderFilter>("all");
  const [orgFilter, setOrgFilter] = useState("");
  const orgId = isUuid(orgFilter) ? orgFilter : "";

  useEffect(() => {
    let mounted = true;

    async function loadPayouts(): Promise<void> {
      configureBrowserClient();
      const result = await listAdminPayoutsV1AdminPayoutsGet({
        headers: getAccessTokenHeaders(),
        query: {
          page: 1,
          page_size: 20,
          status: statusFilter,
          provider: providerFilter,
          ...(orgId ? { org_id: orgId } : {}),
        },
      });

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }

      setError(null);
      setDirectory(result.data);
    }

    void loadPayouts();
    return () => {
      mounted = false;
    };
  }, [statusFilter, providerFilter, orgId]);

  if (loading) {
    return <TableSkeleton />;
  }

  const items = directory?.items ?? [];

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin payouts
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Payout oversight
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Monitor Contributor and Organization payouts, filter by status and
          provider, and investigate failed transfers. Read-only — destination
          account details are never shown.
        </p>
      </header>

      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:grid-cols-2 lg:grid-cols-3">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Status
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) =>
              setStatusFilter(event.target.value as PayoutStatusFilter)
            }
            value={statusFilter}
          >
            <option value="all">All statuses</option>
            <option value="pending">Pending</option>
            <option value="processing">Processing</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Provider
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) =>
              setProviderFilter(event.target.value as PayoutProviderFilter)
            }
            value={providerFilter}
          >
            <option value="all">All providers</option>
            <option value="stripe">Stripe</option>
            <option value="paystack">Paystack</option>
          </select>
        </label>
        <OrgIdFilter onChange={setOrgFilter} value={orgFilter} />
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted shadow-sm">
          No payouts match these filters.
        </div>
      ) : (
        <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
          {/* Table header — desktop/tablet only */}
          <div className="hidden md:grid md:grid-cols-[1.4fr_1fr_1fr_0.9fr_1.1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
            <div>Beneficiary</div>
            <div>Amount</div>
            <div>Provider</div>
            <div>Status</div>
            <div className="text-right">Initiated</div>
          </div>

          {items.map((item) => (
            <article
              className="
                flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm
                md:grid md:grid-cols-[1.4fr_1fr_1fr_0.9fr_1.1fr] md:items-center md:gap-4
                md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                md:hover:bg-surface-2/30 transition-colors
              "
              key={item.payout_id}
              role="article"
            >
              {/* Beneficiary cell */}
              <div className="grid gap-0.5">
                <span className="inline-flex w-fit items-center rounded-md border border-border-default bg-surface-2 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-foreground-muted">
                  {item.beneficiary_type}
                </span>
                {item.beneficiary_type === "org" ? (
                  <OrgLink name={item.beneficiary_name} orgId={item.beneficiary_id} />
                ) : (
                  <p
                    className="text-sm font-semibold text-foreground break-all md:text-xs"
                    title={item.beneficiary_id}
                  >
                    {item.beneficiary_name || shortId(item.beneficiary_id)}
                  </p>
                )}
                {item.provider_ref ? (
                  <p className="font-mono text-[11px] text-foreground-subtle break-all">
                    ref: {item.provider_ref}
                  </p>
                ) : null}
              </div>

              {/* Amount cell */}
              <div className="text-sm text-foreground md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Amount
                </span>
                <span className="font-semibold">
                  {formatMoney(item.net_amount, item.currency)}
                </span>
                <span className="block text-xs text-foreground-muted">
                  gross {formatMoney(item.amount, item.currency)}
                </span>
              </div>

              {/* Provider cell */}
              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Provider
                </span>
                <span className="inline-flex items-center rounded-md border border-border-default bg-surface-2 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
                  {item.provider}
                </span>
              </div>

              {/* Status cell */}
              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Status
                </span>
                <span
                  className={[
                    "inline-flex items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                    STATUS_STYLES[item.status],
                  ].join(" ")}
                >
                  {item.status}
                </span>
              </div>

              {/* Initiated cell */}
              <div className="text-sm text-foreground md:text-right md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Initiated
                </span>
                <span>{formatTimestamp(item.initiated_at)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
