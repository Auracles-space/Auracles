"use client";

/**
 * Admin money-movement oversight panel.
 *
 * One investigation surface over the five read-only financial views:
 * payments, the append-only ledger, escrow holdings, webhook delivery, and the
 * audit log. They are tabs rather than separate routes because an admin
 * chasing one failed payment moves between them continuously.
 *
 * Payments name payer and payee organizations (linked to the org detail
 * page) and can be narrowed to one organization.
 *
 * Read-only throughout. Payment credentials, payout destinations, and raw
 * webhook payloads are absent from these APIs by construction, so nothing
 * sensitive can render here.
 *
 * This file is the container: it owns tab and filter state and loading;
 * the filter bar and each tab body live in sibling `admin-money-*` files.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type {
  AdminAuditLogsResponse,
  AdminEscrowDirectoryResponse,
  AdminFinancialEventsResponse,
  AdminTransactionDirectoryResponse,
  AdminWebhookEventsResponse,
} from "@/lib/generated/types.gen";

import { fetchMoneyTab } from "./admin-money-data";
import { AuditView, WebhooksView } from "./admin-money-event-views";
import { MoneyFilters } from "./admin-money-filters";
import { EscrowsView, LedgerView } from "./admin-money-ledger-views";
import { PaymentsView } from "./admin-money-payments-view";
import { ErrorBanner, MONEY_TABS, type MoneyTab } from "./admin-money-primitives";
import { isUuid } from "./admin-org-party";

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
  const [orgFilter, setOrgFilter] = useState("");
  const orgId = isUuid(orgFilter) ? orgFilter : "";

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
    setOrgFilter("");
  }, []);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    async function load(): Promise<void> {
      configureBrowserClient();
      const result = await fetchMoneyTab(tab, {
        status: statusFilter,
        provider: providerFilter,
        reason: reasonFilter,
        providerRef,
        orgId,
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
  }, [tab, statusFilter, providerFilter, reasonFilter, providerRef, orgId]);

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
        onOrgChange={setOrgFilter}
        orgFilter={orgFilter}
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
