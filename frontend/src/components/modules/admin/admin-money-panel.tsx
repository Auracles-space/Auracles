"use client";

/**
 * Admin money-movement oversight panel.
 *
 * One investigation surface over the five read-only financial views:
 * payments, the append-only ledger, escrow holdings, webhook delivery, and the
 * audit log. They are tabs rather than separate routes because an admin
 * chasing one failed payment moves between them continuously.
 *
 * Read-only throughout. Payment credentials, payout destinations, and raw
 * webhook payloads are absent from these APIs by construction, so nothing
 * sensitive can render here.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminAuditLogsV1AdminAuditLogsGet,
  listAdminEscrowsV1AdminEscrowsGet,
  listAdminFinancialEventsV1AdminFinancialEventsGet,
  listAdminTransactionsV1AdminTransactionsGet,
  listAdminWebhookEventsV1AdminWebhookEventsGet,
} from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type {
  AdminAuditLogsResponse,
  AdminEscrowDirectoryResponse,
  AdminFinancialEventsResponse,
  AdminTransactionDirectoryResponse,
  AdminWebhookEventsResponse,
} from "@/lib/generated/types.gen";

import {
  EmptyState,
  ErrorBanner,
  FilterSelect,
  MONEY_TABS,
  PROVIDER_OPTIONS,
  Pill,
  StatCard,
  formatAmount,
  formatTimestamp,
  toneForStatus,
  type MoneyTab,
} from "./admin-money-primitives";

const PAGE_SIZE = 20;

/**
 * Render the tabbed admin money-movement oversight surface.
 */
export function AdminMoneyPanel() {
  const [tab, setTab] = useState<MoneyTab>("payments");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [statusFilter, setStatusFilter] = useState("all");
  const [providerFilter, setProviderFilter] = useState("all");
  const [reasonFilter, setReasonFilter] = useState("");
  const [providerRef, setProviderRef] = useState("");

  const [payments, setPayments] =
    useState<AdminTransactionDirectoryResponse | null>(null);
  const [ledger, setLedger] = useState<AdminFinancialEventsResponse | null>(null);
  const [escrows, setEscrows] = useState<AdminEscrowDirectoryResponse | null>(null);
  const [webhooks, setWebhooks] = useState<AdminWebhookEventsResponse | null>(null);
  const [auditLogs, setAuditLogs] = useState<AdminAuditLogsResponse | null>(null);

  /** Switch tabs, clearing filters that do not carry across views. */
  const selectTab = useCallback((next: MoneyTab) => {
    setTab(next);
    setStatusFilter("all");
    setProviderFilter("all");
    setReasonFilter("");
    setProviderRef("");
  }, []);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    async function load(): Promise<void> {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const paging = { page: 1, page_size: PAGE_SIZE };

      const result = await (async () => {
        if (tab === "payments") {
          return listAdminTransactionsV1AdminTransactionsGet({
            headers,
            query: {
              ...paging,
              status: statusFilter,
              provider: providerFilter,
              ...(providerRef ? { provider_ref: providerRef } : {}),
            },
          });
        }
        if (tab === "ledger") {
          return listAdminFinancialEventsV1AdminFinancialEventsGet({
            headers,
            query: {
              ...paging,
              provider: providerFilter,
              ...(reasonFilter ? { reason_code: reasonFilter } : {}),
            },
          });
        }
        if (tab === "escrows") {
          return listAdminEscrowsV1AdminEscrowsGet({
            headers,
            query: { ...paging, status: statusFilter },
          });
        }
        if (tab === "webhooks") {
          return listAdminWebhookEventsV1AdminWebhookEventsGet({
            headers,
            query: { ...paging, status: statusFilter, provider: providerFilter },
          });
        }
        return listAdminAuditLogsV1AdminAuditLogsGet({
          headers,
          query: { ...paging, ...(reasonFilter ? { action: reasonFilter } : {}) },
        });
      })();

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setError(null);

      if (tab === "payments") {
        setPayments(result.data as AdminTransactionDirectoryResponse);
      } else if (tab === "ledger") {
        setLedger(result.data as AdminFinancialEventsResponse);
      } else if (tab === "escrows") {
        setEscrows(result.data as AdminEscrowDirectoryResponse);
      } else if (tab === "webhooks") {
        setWebhooks(result.data as AdminWebhookEventsResponse);
      } else {
        setAuditLogs(result.data as AdminAuditLogsResponse);
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [tab, statusFilter, providerFilter, reasonFilter, providerRef]);

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin money
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Money movement
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Trace every payment, escrow hold, and provider webhook end to end. A
          payment&rsquo;s status records only where it ended up; the ledger keeps
          each step and why it failed.
        </p>
      </header>

      <nav
        aria-label="Money oversight views"
        className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1"
      >
        {MONEY_TABS.map((item) => (
          <button
            aria-current={tab === item.id ? "page" : undefined}
            className={[
              "min-h-11 shrink-0 rounded-xl border px-4 text-sm font-semibold transition-colors",
              tab === item.id
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-border-default bg-surface-1 text-foreground-muted hover:bg-surface-2/50",
            ].join(" ")}
            key={item.id}
            onClick={() => selectTab(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>

      <MoneyFilters
        onProviderChange={setProviderFilter}
        onProviderRefChange={setProviderRef}
        onReasonChange={setReasonFilter}
        onStatusChange={setStatusFilter}
        providerFilter={providerFilter}
        providerRef={providerRef}
        reasonFilter={reasonFilter}
        statusFilter={statusFilter}
        tab={tab}
      />

      {error ? <ErrorBanner message={error} /> : null}

      {loading ? (
        <TableSkeleton />
      ) : tab === "payments" ? (
        <PaymentsView data={payments} />
      ) : tab === "ledger" ? (
        <LedgerView data={ledger} />
      ) : tab === "escrows" ? (
        <EscrowsView data={escrows} />
      ) : tab === "webhooks" ? (
        <WebhooksView data={webhooks} />
      ) : (
        <AuditView data={auditLogs} />
      )}
    </section>
  );
}

type MoneyFiltersProps = {
  tab: MoneyTab;
  statusFilter: string;
  providerFilter: string;
  reasonFilter: string;
  providerRef: string;
  onStatusChange: (value: string) => void;
  onProviderChange: (value: string) => void;
  onReasonChange: (value: string) => void;
  onProviderRefChange: (value: string) => void;
};

/** Status options per tab; empty means the tab has no status filter. */
const STATUS_OPTIONS: Record<MoneyTab, { value: string; label: string }[]> = {
  payments: [
    { value: "all", label: "All statuses" },
    { value: "pending", label: "Pending" },
    { value: "completed", label: "Completed" },
    { value: "failed", label: "Failed" },
    { value: "refunded", label: "Refunded" },
  ],
  ledger: [],
  escrows: [
    { value: "all", label: "All statuses" },
    { value: "held", label: "Held" },
    { value: "released", label: "Released" },
    { value: "refunded", label: "Refunded" },
  ],
  webhooks: [
    { value: "all", label: "All statuses" },
    { value: "received", label: "Received" },
    { value: "processed", label: "Processed" },
    { value: "failed", label: "Failed" },
  ],
  audit: [],
};

/**
 * Render the filter row appropriate to the active tab.
 *
 * @param props - Current filter values and their change handlers.
 */
function MoneyFilters({
  tab,
  statusFilter,
  providerFilter,
  reasonFilter,
  providerRef,
  onStatusChange,
  onProviderChange,
  onReasonChange,
  onProviderRefChange,
}: MoneyFiltersProps) {
  const statuses = STATUS_OPTIONS[tab];
  const showProvider = tab !== "audit" && tab !== "escrows";
  const showReason = tab === "ledger";
  const showAction = tab === "audit";
  const showRef = tab === "payments";

  if (!statuses.length && !showProvider && !showReason && !showAction) {
    return null;
  }

  return (
    <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:grid-cols-2 lg:grid-cols-3">
      {statuses.length ? (
        <FilterSelect
          label="Status"
          onChange={onStatusChange}
          options={statuses}
          value={statusFilter}
        />
      ) : null}
      {showProvider ? (
        <FilterSelect
          label="Provider"
          onChange={onProviderChange}
          options={PROVIDER_OPTIONS}
          value={providerFilter}
        />
      ) : null}
      {showReason ? (
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Failure cause
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => onReasonChange(event.target.value.trim())}
            placeholder="insufficient_funds"
            value={reasonFilter}
          />
        </label>
      ) : null}
      {showAction ? (
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Action
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => onReasonChange(event.target.value.trim())}
            placeholder="payout_failed"
            value={reasonFilter}
          />
        </label>
      ) : null}
      {showRef ? (
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Provider reference
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 font-mono text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => onProviderRefChange(event.target.value.trim())}
            placeholder="pi_3Q… / ref_…"
            value={providerRef}
          />
        </label>
      ) : null}
    </section>
  );
}

/**
 * Render the payments directory, each row linking to its full timeline.
 *
 * @param props.data - Transaction directory response, or null before load.
 */
function PaymentsView({ data }: { data: AdminTransactionDirectoryResponse | null }) {
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
          <li key={item.transaction_id}>
            <Link
              className="flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm transition-colors md:grid md:grid-cols-[1.5fr_1fr_0.9fr_1.4fr] md:items-center md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none md:hover:bg-surface-2/30"
              href={`/admin/money/${item.transaction_id}`}
            >
              <div className="grid gap-0.5">
                <Pill>{item.transaction_type}</Pill>
                <p className="break-all font-mono text-xs text-foreground-muted">
                  {item.transaction_id}
                </p>
                {item.provider_ref ? (
                  <p className="break-all font-mono text-[11px] text-foreground-subtle">
                    ref: {item.provider_ref}
                  </p>
                ) : null}
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
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Render the append-only ledger feed.
 *
 * @param props.data - Financial events response, or null before load.
 */
function LedgerView({ data }: { data: AdminFinancialEventsResponse | null }) {
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
function EscrowsView({ data }: { data: AdminEscrowDirectoryResponse | null }) {
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

/**
 * Render the provider webhook delivery log, including stored errors.
 *
 * @param props.data - Webhook events response, or null before load.
 */
function WebhooksView({ data }: { data: AdminWebhookEventsResponse | null }) {
  const items = data?.items ?? [];
  if (!items.length) {
    return <EmptyState message="No webhook deliveries match these filters." />;
  }

  return (
    <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
      {items.map((event) => (
        <li
          className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.4fr_0.8fr_0.8fr_1.6fr] md:items-start md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none"
          key={event.event_id}
        >
          <div className="grid gap-0.5">
            <span className="text-sm font-semibold text-foreground">
              {event.event_type}
            </span>
            <span className="break-all font-mono text-[11px] text-foreground-subtle">
              {event.provider_event_id}
            </span>
          </div>
          <Pill>{event.provider}</Pill>
          <Pill tone={toneForStatus(event.status)}>{event.status}</Pill>
          <div className="grid gap-1 text-xs md:text-right">
            {event.error ? (
              <span className="break-words font-medium text-error">
                {event.error}
              </span>
            ) : null}
            <span className="text-foreground-subtle">
              {formatTimestamp(event.received_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Render the filtered audit log view.
 *
 * @param props.data - Audit log response, or null before load.
 */
function AuditView({ data }: { data: AdminAuditLogsResponse | null }) {
  const items = data?.items ?? [];
  if (!items.length) {
    return <EmptyState message="No audit entries match these filters." />;
  }

  return (
    <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
      {items.map((log) => (
        <li
          className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.2fr_1fr_1.4fr] md:items-center md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none"
          key={log.log_id}
        >
          <span className="text-sm font-semibold text-foreground">{log.action}</span>
          <div className="grid gap-0.5">
            <Pill>{log.target_type}</Pill>
            {log.target_id ? (
              <span className="break-all font-mono text-[11px] text-foreground-subtle">
                {log.target_id}
              </span>
            ) : null}
          </div>
          <div className="grid gap-0.5 text-xs md:text-right">
            <span className="break-all font-mono text-foreground-muted">
              {log.actor_id ?? "system"}
            </span>
            <span className="text-foreground-subtle">
              {formatTimestamp(log.created_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
