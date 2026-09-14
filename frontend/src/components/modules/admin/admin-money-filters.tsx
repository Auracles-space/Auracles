"use client";

/**
 * Filter bar for the admin money-movement oversight panel.
 *
 * Shows only the filters the active tab honours: status, provider, failure
 * cause (ledger), action (audit), and provider reference plus organization ID
 * (payments).
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import {
  FilterSelect,
  PROVIDER_OPTIONS,
  type MoneyTab,
} from "./admin-money-primitives";
import { OrgIdFilter } from "./admin-org-party";

/** Current filter values and change handlers for the active tab. */
export type MoneyFiltersProps = {
  tab: MoneyTab;
  statusFilter: string;
  providerFilter: string;
  reasonFilter: string;
  providerRef: string;
  orgFilter: string;
  onOrgChange: (value: string) => void;
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
export function MoneyFilters({
  tab,
  statusFilter,
  providerFilter,
  reasonFilter,
  providerRef,
  orgFilter,
  onOrgChange,
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
      {showRef ? <OrgIdFilter onChange={onOrgChange} value={orgFilter} /> : null}
    </section>
  );
}
