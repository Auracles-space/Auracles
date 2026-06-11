/**
 * Developer portal component tests.
 *
 * Verifies that the Phase 5a Partner Developer dashboard renders generated
 * client data for applications, API keys, analytics, webhooks, and payouts.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeveloperPortal } from "@/components/modules/developer/developer-portal";
import {
  getDeveloperSalesAnalyticsV1DeveloperAnalyticsSalesGet,
  getDeveloperTierProgressV1DeveloperTierGet,
  getDeveloperUsageAnalyticsV1DeveloperAnalyticsUsageGet,
  listApiKeysV1DeveloperApiKeysGet,
  listMyDeveloperApplicationsV1DeveloperApplicationsMineGet,
  listPartnerPayoutsV1DeveloperPayoutsGet,
  listPartnerWebhooksV1DeveloperWebhooksGet,
  listPayoutAccounts,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createApiKeyV1DeveloperApiKeysPost: vi.fn(),
  createPartnerWebhookV1DeveloperWebhooksPost: vi.fn(),
  getDeveloperSalesAnalyticsV1DeveloperAnalyticsSalesGet: vi.fn(),
  getDeveloperTierProgressV1DeveloperTierGet: vi.fn(),
  getDeveloperUsageAnalyticsV1DeveloperAnalyticsUsageGet: vi.fn(),
  listApiKeysV1DeveloperApiKeysGet: vi.fn(),
  listMyDeveloperApplicationsV1DeveloperApplicationsMineGet: vi.fn(),
  listPartnerPayoutsV1DeveloperPayoutsGet: vi.fn(),
  listPartnerWebhooksV1DeveloperWebhooksGet: vi.fn(),
  listPayoutAccounts: vi.fn(),
  requestPartnerPayoutV1DeveloperPayoutsPost: vi.fn(),
  submitDeveloperApplicationV1DeveloperApplicationsPost: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

describe("DeveloperPortal", () => {
  beforeEach(() => {
    vi.mocked(listMyDeveloperApplicationsV1DeveloperApplicationsMineGet).mockResolvedValue(
      ok({
        applications: [
          {
            admin_feedback: null,
            company_name: "Partner Systems Inc.",
            created_at: "2026-06-11T10:00:00Z",
            id: "app_1",
            reviewed_at: "2026-06-11T11:00:00Z",
            reviewed_by: "admin_1",
            status: "approved",
            use_case: "Embed Auracles Framework discovery in a CRM.",
            user_id: "user_1",
            website: "https://partners.example.com",
          },
        ],
      }),
    );
    vi.mocked(listApiKeysV1DeveloperApiKeysGet).mockResolvedValue(
      ok({
        api_keys: [
          {
            created_at: "2026-06-11T10:00:00Z",
            expires_at: null,
            id: "key_1",
            key_prefix: "ak_live_123",
            last_used_at: "2026-06-11T12:00:00Z",
            name: "Production CRM",
            revoked_at: null,
            scopes: ["catalog:read", "purchase:write"],
            status: "active",
          },
        ],
      }),
    );
    vi.mocked(getDeveloperTierProgressV1DeveloperTierGet).mockResolvedValue(
      ok({
        current_rate: "0.0800",
        current_tier: 2,
        next_tier: 3,
        next_tier_sales_required: 410,
        prior_30d_sales_count: 90,
        tier_recalculated_at: null,
        tiers: [],
      }),
    );
    vi.mocked(getDeveloperUsageAnalyticsV1DeveloperAnalyticsUsageGet).mockResolvedValue(
      ok({
        average_response_ms: 133,
        by_endpoint: [
          {
            average_response_ms: 80,
            client_error_count: 1,
            endpoint: "/v1/partner/catalog",
            method: "GET",
            request_count: 2,
            server_error_count: 0,
            success_count: 1,
          },
        ],
        client_error_count: 1,
        server_error_count: 1,
        success_count: 8,
        total_requests: 10,
        window_days: 30,
      }),
    );
    vi.mocked(getDeveloperSalesAnalyticsV1DeveloperAnalyticsSalesGet).mockResolvedValue(
      ok({
        by_framework: [
          {
            commission_amount: "17.50",
            framework_id: "framework_1",
            framework_title: "Governance Operating Model",
            gross_sale_amount: "350.00",
            sale_count: 3,
          },
        ],
        cleared_commission_amount: "10.00",
        gross_sale_amount: "350.00",
        paid_commission_amount: "0.00",
        pending_commission_amount: "5.00",
        status_counts: { cleared: 1, paid: 0, pending: 1, voided: 1 },
        total_commission_amount: "17.50",
        total_sales: 3,
        voided_commission_amount: "2.50",
        window_days: 30,
      }),
    );
    vi.mocked(listPartnerWebhooksV1DeveloperWebhooksGet).mockResolvedValue(
      ok({
        webhooks: [
          {
            active: true,
            created_at: "2026-06-11T10:00:00Z",
            events: ["purchase.confirmed"],
            id: "webhook_1",
            url: "https://partners.example.com/webhooks/auracles",
          },
        ],
      }),
    );
    vi.mocked(listPartnerPayoutsV1DeveloperPayoutsGet).mockResolvedValue(
      ok({
        payouts: [
          {
            amount: "75.00",
            completed_at: null,
            currency: "USD",
            id: "payout_1",
            initiated_at: "2026-06-11T10:00:00Z",
            payout_account_id: "acct_1",
            provider_ref: null,
            status: "pending",
          },
        ],
      }),
    );
    vi.mocked(listPayoutAccounts).mockResolvedValue(
      ok({
        payout_accounts: [
          {
            account_type: "express",
            created_at: "2026-06-11T10:00:00Z",
            id: "acct_1",
            is_default: true,
            provider: "stripe",
            provider_account_ref: "acct_1234",
            verified_at: "2026-06-11T10:00:00Z",
          },
        ],
      }),
    );
  });

  it("renders the approved Developer workspace from generated-client data", async () => {
    render(<DeveloperPortal />);

    expect(await screen.findByText("Developer platform")).toBeInTheDocument();
    expect(screen.getByText("$17.50")).toBeInTheDocument();
    expect(screen.getAllByText("Tier 2")).toHaveLength(2);
    expect(screen.getByText("Production CRM")).toBeInTheDocument();
    expect(screen.getByText("Governance Operating Model")).toBeInTheDocument();
    expect(screen.getByText("/v1/partner/catalog")).toBeInTheDocument();
    expect(
      screen.getByText("https://partners.example.com/webhooks/auracles"),
    ).toBeInTheDocument();
    expect(screen.getByText("payout_1")).toBeInTheDocument();
  });
});
