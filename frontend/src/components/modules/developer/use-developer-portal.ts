"use client";

/**
 * Developer portal state hook.
 *
 * Loads Partner Developer API state and exposes mutation handlers for
 * applications, API keys, webhooks, and Partner payout requests.
 */
import { useEffect, useMemo, useState } from "react";

import type { ApplicationPayload } from "@/components/modules/developer/developer-portal-application";
import {
  emptyDeveloperPortalState,
  type DeveloperPortalState,
} from "@/components/modules/developer/developer-portal-state";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  createApiKeyV1DeveloperApiKeysPost,
  createPartnerWebhookV1DeveloperWebhooksPost,
  getDeveloperSalesAnalyticsV1DeveloperAnalyticsSalesGet,
  getDeveloperTierProgressV1DeveloperTierGet,
  getDeveloperUsageAnalyticsV1DeveloperAnalyticsUsageGet,
  listApiKeysV1DeveloperApiKeysGet,
  listMyDeveloperApplicationsV1DeveloperApplicationsMineGet,
  listPartnerPayoutsV1DeveloperPayoutsGet,
  listPartnerWebhooksV1DeveloperWebhooksGet,
  listPayoutAccounts,
  requestPartnerPayoutV1DeveloperPayoutsPost,
  submitDeveloperApplicationV1DeveloperApplicationsPost,
} from "@/lib/generated/sdk.gen";

/**
 * Return Developer portal data, derived state, and mutation handlers.
 */
export function useDeveloperPortal() {
  const [data, setData] = useState<DeveloperPortalState>(
    emptyDeveloperPortalState,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [oneTimeSecret, setOneTimeSecret] = useState<string | null>(null);
  const [rawApiKey, setRawApiKey] = useState<string | null>(null);

  async function loadPortal() {
    configureBrowserClient();
    setError(null);
    const headers = getAccessTokenHeaders();

    const applications = await listMyDeveloperApplicationsV1DeveloperApplicationsMineGet({ headers });

    if (!applications.response.ok || !applications.data) {
      setError(describeGeneratedError(applications.error));
      setLoading(false);
      return;
    }

    const appList = applications.data.applications;
    const latestApp = appList[0] ?? null;
    const isApproved = latestApp?.status === "approved";

    if (isApproved) {
      const [
        apiKeys,
        tier,
        usage,
        sales,
        webhooks,
        payouts,
        payoutAccounts,
      ] = await Promise.all([
        listApiKeysV1DeveloperApiKeysGet({ headers }),
        getDeveloperTierProgressV1DeveloperTierGet({ headers }),
        getDeveloperUsageAnalyticsV1DeveloperAnalyticsUsageGet({
          headers,
          query: { days: 30 },
        }),
        getDeveloperSalesAnalyticsV1DeveloperAnalyticsSalesGet({
          headers,
          query: { days: 30 },
        }),
        listPartnerWebhooksV1DeveloperWebhooksGet({ headers }),
        listPartnerPayoutsV1DeveloperPayoutsGet({ headers }),
        listPayoutAccounts({ headers }),
      ]);

      setData({
        applications: appList,
        apiKeys: apiKeys.response.ok && apiKeys.data ? apiKeys.data.api_keys : [],
        payoutAccounts:
          payoutAccounts.response.ok && payoutAccounts.data
            ? payoutAccounts.data.payout_accounts
            : [],
        payouts: payouts.response.ok && payouts.data ? payouts.data.payouts : [],
        sales: sales.response.ok && sales.data ? sales.data : null,
        tier: tier.response.ok && tier.data ? tier.data : null,
        usage: usage.response.ok && usage.data ? usage.data : null,
        webhooks:
          webhooks.response.ok && webhooks.data ? webhooks.data.webhooks : [],
      });
    } else {
      setData({
        applications: appList,
        apiKeys: [],
        payoutAccounts: [],
        payouts: [],
        sales: null,
        tier: null,
        usage: null,
        webhooks: [],
      });
    }
    setLoading(false);
  }

  useEffect(() => {
    void loadPortal();
  }, []);

  const latestApplication = data.applications[0] ?? null;
  const approved = latestApplication?.status === "approved";
  const verifiedPayoutAccounts = useMemo(
    () => data.payoutAccounts.filter((account) => account.verified_at),
    [data.payoutAccounts],
  );

  async function handleApplicationSubmit(payload: ApplicationPayload) {
    configureBrowserClient();
    const result = await submitDeveloperApplicationV1DeveloperApplicationsPost({
      body: payload,
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setData((current) => ({
      ...current,
      applications: [result.data, ...current.applications],
    }));
  }

  async function handleApiKeyCreate(name: string, scopes: string[]) {
    configureBrowserClient();
    const result = await createApiKeyV1DeveloperApiKeysPost({
      body: { name, scopes },
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setRawApiKey(result.data.raw_key);
    setData((current) => ({
      ...current,
      apiKeys: [result.data, ...current.apiKeys],
    }));
  }

  async function handleWebhookCreate(url: string, events: string[]) {
    configureBrowserClient();
    const result = await createPartnerWebhookV1DeveloperWebhooksPost({
      body: { events, url },
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setOneTimeSecret(result.data.secret);
    setData((current) => ({
      ...current,
      webhooks: [result.data, ...current.webhooks],
    }));
  }

  async function handlePayoutRequest(
    amount: string,
    payoutAccountId: string,
    totpCode: string,
  ) {
    configureBrowserClient();
    const result = await requestPartnerPayoutV1DeveloperPayoutsPost({
      body: {
        amount,
        currency: "USD",
        payout_account_id: payoutAccountId,
        totp_code: totpCode,
      },
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setData((current) => ({
      ...current,
      payouts: [result.data, ...current.payouts],
    }));
  }

  return {
    approved,
    data,
    error,
    handleApiKeyCreate,
    handleApplicationSubmit,
    handlePayoutRequest,
    handleWebhookCreate,
    latestApplication,
    loading,
    oneTimeSecret,
    rawApiKey,
    verifiedPayoutAccounts,
  };
}
