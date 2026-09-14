"use client";

/**
 * Payments directory tab of the admin money-movement oversight panel.
 *
 * A card stack on phones and a table-like row list from md. Each row opens the
 * payment's full trace; payer and payee organizations link to their detail
 * page. Every amount is formatted in that row's own currency.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import Link from "next/link";

import type { AdminTransactionDirectoryResponse } from "@/lib/generated/types.gen";

import {
  EmptyState,
  Pill,
  StatCard,
  formatAmount,
  formatTimestamp,
  toneForStatus,
} from "./admin-money-primitives";
import { PartyName } from "./admin-org-party";

/**
 * Render the payments directory, each row linking to its full timeline.
 *
 * @param props.data - Transaction directory response, or null before load.
 */
export function PaymentsView({ data }: { data: AdminTransactionDirectoryResponse | null }) {
  const items = data?.items ?? [];
  const failed = items.filter((item) => item.status === "failed").length;

  if (!items.length) {
    return <EmptyState message="No payments match these filters." />;
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Payments" value={String(data?.total ?? 0)} />
        <StatCard
          label="Failed on this page"
          tone={failed ? "error" : "default"}
          value={String(failed)}
        />
      </div>
      <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
        {items.map((item) => (
          <li
            className="relative flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm transition-colors md:grid md:grid-cols-[1.5fr_1.3fr_1fr_0.9fr_1.4fr] md:items-center md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none md:hover:bg-surface-2/30"
            key={item.transaction_id}
          >
            <div className="grid gap-0.5">
              <Pill>{item.transaction_type}</Pill>
              {/* Stretched link: the whole row opens the trace, while the
                  org links above it (z-10) stay independently clickable. */}
              <Link
                className="break-all font-mono text-xs text-foreground-muted after:absolute after:inset-0 after:content-['']"
                href={`/admin/money/${item.transaction_id}`}
              >
                {item.transaction_id}
              </Link>
              {item.provider_ref ? (
                <p className="break-all font-mono text-[11px] text-foreground-subtle">
                  ref: {item.provider_ref}
                </p>
              ) : null}
            </div>
            <div className="grid gap-1 text-xs">
              <span className="flex flex-wrap items-center gap-x-2">
                <span className="font-semibold uppercase tracking-wider text-foreground-muted">
                  Payer
                </span>
                <PartyName
                  orgId={item.payer_org_id}
                  orgName={item.payer_org_name}
                  userId={item.payer_id}
                />
              </span>
              <span className="flex flex-wrap items-center gap-x-2">
                <span className="font-semibold uppercase tracking-wider text-foreground-muted">
                  Payee
                </span>
                <PartyName
                  orgId={item.payee_org_id}
                  orgName={item.payee_org_name}
                  userId={item.payee_id}
                />
              </span>
            </div>
            <div className="text-sm text-foreground md:text-xs">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-foreground-muted md:hidden">
                Amount
              </span>
              <span className="font-semibold">
                {formatAmount(item.amount, item.currency)}
              </span>
              <span className="block text-xs text-foreground-muted">
                net {formatAmount(item.net_amount, item.currency)}
              </span>
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-foreground-muted md:hidden">
                Status
              </span>
              <Pill tone={toneForStatus(item.status)}>{item.status}</Pill>
            </div>
            <div className="text-sm md:text-right md:text-xs">
              {item.failure_reason_code ? (
                <span className="font-semibold text-error">
                  {item.failure_reason_code}
                </span>
              ) : (
                <span className="text-foreground-muted">
                  {item.provider ?? "—"}
                </span>
              )}
              <span className="block text-xs text-foreground-subtle">
                {formatTimestamp(item.created_at)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
