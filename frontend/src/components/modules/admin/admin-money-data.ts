/**
 * Data loading for the admin money-movement oversight panel.
 *
 * Maps each money tab to its read-only admin endpoint and the query
 * parameters that tab honours, so the panel container only owns state.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import {
  listAdminAuditLogsV1AdminAuditLogsGet,
  listAdminEscrowsV1AdminEscrowsGet,
  listAdminFinancialEventsV1AdminFinancialEventsGet,
  listAdminTransactionsV1AdminTransactionsGet,
  listAdminWebhookEventsV1AdminWebhookEventsGet,
} from "@/lib/generated/sdk.gen";

import type { MoneyTab } from "./admin-money-primitives";

const PAGE_SIZE = 20;

/** Filter values the money tabs may send; each tab uses only its own subset. */
export type MoneyQueryFilters = {
  status: string;
  provider: string;
  reason: string;
  providerRef: string;
  /** Validated organization UUID, or empty when no org filter applies. */
  orgId: string;
};

/**
 * Fetch the first page of the given money tab with its applicable filters.
 *
 * The browser client must already be configured by the caller.
 *
 * @param tab - Active money oversight view.
 * @param filters - Current filter values.
 * @returns The generated client's result for that tab's endpoint.
 */
export async function fetchMoneyTab(tab: MoneyTab, filters: MoneyQueryFilters) {
  const headers = getAccessTokenHeaders();
  const paging = { page: 1, page_size: PAGE_SIZE };
  const { status, provider, reason, providerRef, orgId } = filters;

  if (tab === "payments") {
    return listAdminTransactionsV1AdminTransactionsGet({
      headers,
      query: {
        ...paging,
        status,
        provider,
        ...(providerRef ? { provider_ref: providerRef } : {}),
        ...(orgId ? { org_id: orgId } : {}),
      },
    });
  }
  if (tab === "ledger") {
    return listAdminFinancialEventsV1AdminFinancialEventsGet({
      headers,
      query: {
        ...paging,
        provider,
        ...(reason ? { reason_code: reason } : {}),
      },
    });
  }
  if (tab === "escrows") {
    return listAdminEscrowsV1AdminEscrowsGet({
      headers,
      query: { ...paging, status },
    });
  }
  if (tab === "webhooks") {
    return listAdminWebhookEventsV1AdminWebhookEventsGet({
      headers,
      query: { ...paging, status, provider },
    });
  }
  return listAdminAuditLogsV1AdminAuditLogsGet({
    headers,
    query: { ...paging, ...(reason ? { action: reason } : {}) },
  });
}
