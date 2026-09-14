"use client";

/**
 * Ledger and escrow tabs of the admin money-movement oversight panel.
 *
 * The ledger is the append-only record of each money step and why it failed;
 * escrows are current holdings. Amounts use each row's own currency.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import type {
  AdminEscrowDirectoryResponse,
  AdminFinancialEventsResponse,
} from "@/lib/generated/types.gen";

import {
  EmptyState,
  Pill,
  formatAmount,
  formatTimestamp,
  toneForStatus,
} from "./admin-money-primitives";

/**
 * Render the append-only ledger feed.
 *
 * @param props.data - Financial events response, or null before load.
 */
export function LedgerView({ data }: { data: AdminFinancialEventsResponse | null }) {
  const items = data?.items ?? [];
  if (!items.length) {
    return <EmptyState message="No ledger events match these filters." />;
  }

  return (
    <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
      {items.map((event) => (
        <li
          className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.4fr_1fr_1.6fr] md:items-start md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none"
          key={event.event_id}
        >
          <div className="grid gap-1">
            <span className="text-sm font-semibold text-foreground">
              {event.event_type}
            </span>
            <span className="break-all font-mono text-[11px] text-foreground-subtle">
              {event.entity_type} · {event.entity_id}
            </span>
          </div>
          <div className="grid gap-1 text-xs text-foreground-muted">
            {event.from_status || event.to_status ? (
              <span>
                {event.from_status ?? "—"} → {event.to_status ?? "—"}
              </span>
            ) : null}
            {event.amount && event.currency ? (
              <span className="font-semibold text-foreground">
                {formatAmount(event.amount, event.currency)}
              </span>
            ) : null}
          </div>
          <div className="grid gap-1 text-xs md:text-right">
            {event.reason_code ? (
              <span className="font-semibold text-error">{event.reason_code}</span>
            ) : null}
            {event.reason_message ? (
              <span className="text-foreground-muted">{event.reason_message}</span>
            ) : null}
            <span className="text-foreground-subtle">
              {formatTimestamp(event.occurred_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Render current escrow holdings.
 *
 * @param props.data - Escrow directory response, or null before load.
 */
export function EscrowsView({ data }: { data: AdminEscrowDirectoryResponse | null }) {
  const items = data?.items ?? [];
  if (!items.length) {
    return <EmptyState message="No escrows match these filters." />;
  }

  return (
    <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
      {items.map((escrow) => (
        <li
          className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.4fr_1fr_0.8fr_1fr] md:items-center md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none"
          key={escrow.escrow_id}
        >
          <div className="grid gap-0.5">
            <Pill>{escrow.ref_type}</Pill>
            <span className="break-all font-mono text-xs text-foreground-muted">
              {escrow.ref_id}
            </span>
          </div>
          <span className="text-sm font-semibold text-foreground md:text-xs">
            {formatAmount(escrow.amount, escrow.currency)}
          </span>
          <Pill tone={toneForStatus(escrow.status)}>{escrow.status}</Pill>
          <span className="text-xs text-foreground-subtle md:text-right">
            held {formatTimestamp(escrow.held_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}
