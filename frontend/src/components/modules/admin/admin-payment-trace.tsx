"use client";

/**
 * Admin single-payment trace.
 *
 * Reconstructs one payment end to end from the financial ledger: every
 * recorded state change in order, with the normalized cause attached to each
 * failure. This is the only place intermediate states survive — the status
 * column keeps just the final value — so the timeline is the page, not a
 * footnote to it. Payer and payee organizations are named and linked.
 *
 * Maps to: admin financial oversight (per-payment traceability).
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAdminTransactionDetailV1AdminTransactionsTransactionIdGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type { AdminTransactionDetailResponse } from "@/lib/generated/types.gen";

import {
  EmptyState,
  ErrorBanner,
  Pill,
  formatAmount,
  formatTimestamp,
  toneForStatus,
} from "./admin-money-primitives";
import { PartyName } from "./admin-org-party";

type AdminPaymentTraceProps = {
  transactionId: string;
};

/**
 * Render one payment's summary, escrow holdings, and ledger timeline.
 *
 * @param props.transactionId - Transaction to trace.
 */
export function AdminPaymentTrace({ transactionId }: AdminPaymentTraceProps) {
  const [detail, setDetail] = useState<AdminTransactionDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load(): Promise<void> {
      configureBrowserClient();
      const result =
        await getAdminTransactionDetailV1AdminTransactionsTransactionIdGet({
          headers: getAccessTokenHeaders(),
          path: { transaction_id: transactionId },
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
      setDetail(result.data);
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [transactionId]);

  if (loading) {
    return <TableSkeleton />;
  }

  if (error) {
    return (
      <section className="grid gap-6">
        <BackLink />
        <ErrorBanner message={error} />
      </section>
    );
  }

  if (!detail) {
    return (
      <section className="grid gap-6">
        <BackLink />
        <EmptyState message="This payment could not be loaded." />
      </section>
    );
  }

  const { transaction, escrows, timeline } = detail;

  return (
    <section className="grid gap-6">
      <BackLink />

      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={toneForStatus(transaction.status)}>{transaction.status}</Pill>
          <Pill>{transaction.transaction_type}</Pill>
          {transaction.provider ? <Pill>{transaction.provider}</Pill> : null}
        </div>
        <h2 className="mt-3 font-heading text-3xl font-bold text-foreground">
          {formatAmount(transaction.amount, transaction.currency)}
        </h2>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <Detail label="Net" value={formatAmount(transaction.net_amount, transaction.currency)} />
          <Detail
            label="Platform commission"
            value={formatAmount(transaction.platform_commission, transaction.currency)}
          />
          <PartyDetail label="Payer">
            <PartyName
              orgId={transaction.payer_org_id}
              orgName={transaction.payer_org_name}
              userId={transaction.payer_id}
            />
          </PartyDetail>
          <PartyDetail label="Payee">
            <PartyName
              orgId={transaction.payee_org_id}
              orgName={transaction.payee_org_name}
              userId={transaction.payee_id}
            />
          </PartyDetail>
          <Detail label="Created" value={formatTimestamp(transaction.created_at)} />
          <Detail label="Transaction ID" mono value={transaction.transaction_id} />
          {transaction.provider_ref ? (
            <Detail label="Provider reference" mono value={transaction.provider_ref} />
          ) : null}
          {transaction.failure_reason_code ? (
            <Detail
              label="Failure cause"
              tone="error"
              value={transaction.failure_reason_code}
            />
          ) : null}
        </dl>
      </header>

      <section className="grid gap-4">
        <h3 className="font-heading text-xl font-bold text-foreground">Timeline</h3>
        {timeline.length === 0 ? (
          <EmptyState message="No ledger events recorded for this payment yet." />
        ) : (
          <ol className="grid gap-3">
            {timeline.map((event) => (
              <li
                className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.2fr_1fr_1.4fr] md:items-start md:gap-4"
                key={event.event_id}
              >
                <div className="grid gap-1">
                  <span className="text-sm font-semibold text-foreground">
                    {event.event_type}
                  </span>
                  <span className="text-xs text-foreground-subtle">
                    {formatTimestamp(event.occurred_at)}
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
                    <span className="font-semibold text-error">
                      {event.reason_code}
                    </span>
                  ) : null}
                  {event.reason_message ? (
                    <span className="text-foreground-muted">
                      {event.reason_message}
                    </span>
                  ) : null}
                  {event.provider_ref ? (
                    <span className="break-all font-mono text-[11px] text-foreground-subtle">
                      {event.provider_ref}
                    </span>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {escrows.length > 0 ? (
        <section className="grid gap-4">
          <h3 className="font-heading text-xl font-bold text-foreground">Escrow</h3>
          <ul className="grid gap-3">
            {escrows.map((escrow) => (
              <li
                className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.2fr_1fr_0.8fr_1fr] md:items-center md:gap-4"
                key={escrow.escrow_id}
              >
                <div className="grid gap-0.5">
                  <Pill>{escrow.ref_type}</Pill>
                  <span className="break-all font-mono text-xs text-foreground-muted">
                    {escrow.ref_id}
                  </span>
                </div>
                <span className="text-sm font-semibold text-foreground">
                  {formatAmount(escrow.amount, escrow.currency)}
                </span>
                <Pill tone={toneForStatus(escrow.status)}>{escrow.status}</Pill>
                <span className="text-xs text-foreground-subtle md:text-right">
                  {escrow.released_at
                    ? `released ${formatTimestamp(escrow.released_at)}`
                    : `held ${formatTimestamp(escrow.held_at)}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

/** Render the link back to the money-oversight directory. */
function BackLink() {
  return (
    <Link
      className="inline-flex min-h-11 w-fit items-center gap-2 text-sm font-semibold text-foreground-muted transition-colors hover:text-foreground"
      href="/admin/money"
    >
      <span aria-hidden="true">&larr;</span> Money movement
    </Link>
  );
}

/**
 * Render one labelled detail field.
 *
 * @param props.label - Field caption.
 * @param props.value - Field value.
 * @param props.mono - Render the value in a monospace face for identifiers.
 * @param props.tone - Set to "error" to highlight a failure cause.
 */
function Detail({
  label,
  value,
  mono = false,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "error";
}) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
        {label}
      </dt>
      <dd
        className={[
          "break-all text-sm",
          mono ? "font-mono text-xs" : "",
          tone === "error" ? "font-semibold text-error" : "text-foreground",
        ].join(" ")}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Render a labelled detail whose value is a component (a link or id).
 *
 * @param props.label - Field caption.
 * @param props.children - Rendered value.
 */
function PartyDetail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs font-semibold uppercase tracking-wider text-foreground-muted">
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}
