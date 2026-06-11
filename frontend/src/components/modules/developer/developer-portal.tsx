"use client";

/**
 * Developer portal workspace.
 *
 * Provides the Phase 5a Partner Developer dashboard layout. Data loading and
 * mutations live in the companion hook so this component stays presentation-led.
 */
import { ApplicationPanel } from "@/components/modules/developer/developer-portal-application";
import {
  ApiKeysPanel,
  WebhooksPanel,
} from "@/components/modules/developer/developer-portal-controls";
import {
  AnalyticsPanel,
  MetricCard,
  TierPanel,
} from "@/components/modules/developer/developer-portal-panels";
import { PayoutPanel } from "@/components/modules/developer/developer-portal-payouts";
import { useDeveloperPortal } from "@/components/modules/developer/use-developer-portal";
import { formatMoney } from "@/lib/marketplace/format";

/**
 * Render the Developer Platform dashboard and management controls.
 */
export function DeveloperPortal() {
  const {
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
  } = useDeveloperPortal();

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading Developer portal.</p>;
  }

  return (
    <section className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto grid max-w-[1280px] gap-6">
        <header className="mb-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Partner workspace
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            Developer platform
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Manage Partner API access, attributed commissions, webhooks, and
            payout operations from one workspace.
          </p>
        </header>

        {error ? (
          <div className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
            {error}
          </div>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-4">
          <MetricCard
            label="Partner commission"
            value={formatMoney(data.sales?.total_commission_amount ?? "0.00")}
            helper={`${formatMoney(data.sales?.cleared_commission_amount ?? "0.00")} cleared`}
          />
          <MetricCard
            label="Attributed sales"
            value={String(data.sales?.total_sales ?? 0)}
            helper={formatMoney(data.sales?.gross_sale_amount ?? "0.00")}
          />
          <MetricCard
            label="API requests"
            value={String(data.usage?.total_requests ?? 0)}
            helper={`${data.usage?.average_response_ms ?? 0}ms average`}
          />
          <MetricCard
            label="Commission tier"
            value={`Tier ${data.tier?.current_tier ?? 1}`}
            helper={`${Number(data.tier?.current_rate ?? "0") * 100}% rate`}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
          <div className="grid gap-6">
            <ApplicationPanel
              applications={data.applications}
              latestApplication={latestApplication}
              onSubmit={handleApplicationSubmit}
            />
            {approved ? (
              <>
                <AnalyticsPanel sales={data.sales} usage={data.usage} />
                <ApiKeysPanel
                  apiKeys={data.apiKeys}
                  onCreate={handleApiKeyCreate}
                  rawApiKey={rawApiKey}
                />
              </>
            ) : null}
          </div>

          {approved ? (
            <div className="grid content-start gap-6">
              <TierPanel tier={data.tier} />
              <WebhooksPanel
                onCreate={handleWebhookCreate}
                oneTimeSecret={oneTimeSecret}
                webhooks={data.webhooks}
              />
              <PayoutPanel
                onRequest={handlePayoutRequest}
                payouts={data.payouts}
                verifiedAccounts={verifiedPayoutAccounts}
              />
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
