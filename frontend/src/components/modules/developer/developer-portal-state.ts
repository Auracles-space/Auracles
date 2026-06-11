/**
 * Developer portal state types.
 *
 * Centralizes the generated API response shapes used by the Partner Developer
 * dashboard hook and presentation modules.
 */
import type {
  ApiKeyResponse,
  DeveloperApplicationResponse,
  DeveloperSalesAnalyticsResponse,
  DeveloperTierProgressResponse,
  DeveloperUsageAnalyticsResponse,
  PartnerPayoutResponse,
  PartnerWebhookResponse,
  PayoutAccountResponse,
} from "@/lib/generated/types.gen";

export type DeveloperPortalState = {
  applications: DeveloperApplicationResponse[];
  apiKeys: ApiKeyResponse[];
  payoutAccounts: PayoutAccountResponse[];
  payouts: PartnerPayoutResponse[];
  sales: DeveloperSalesAnalyticsResponse | null;
  tier: DeveloperTierProgressResponse | null;
  usage: DeveloperUsageAnalyticsResponse | null;
  webhooks: PartnerWebhookResponse[];
};

export const emptyDeveloperPortalState: DeveloperPortalState = {
  apiKeys: [],
  applications: [],
  payoutAccounts: [],
  payouts: [],
  sales: null,
  tier: null,
  usage: null,
  webhooks: [],
};
