"use client";

/**
 * Developer portal workspace.
 *
 * Provides the Phase 5a Partner Developer dashboard layout. Data loading and
 * mutations live in the companion hook so this component stays presentation-led.
 */
import { useState } from "react";

import { DeveloperApiUsage } from "@/components/modules/developer/developer-api-usage";
import {
  ApplicationPanel,
  type ApplicationPayload,
} from "@/components/modules/developer/developer-portal-application";
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
import type { DeveloperApplicationResponse } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

type DeveloperOnboardingProps = {
  applications: DeveloperApplicationResponse[];
  latestApplication: DeveloperApplicationResponse | null;
  onSubmit: (payload: ApplicationPayload) => Promise<void>;
};

/**
 * Render developer program information and application form for unapproved users.
 */
function DeveloperOnboarding({
  applications,
  latestApplication,
  onSubmit,
}: DeveloperOnboardingProps) {
  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-[1fr_1.2fr]">
      {/* Left side: Program benefits bento block */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm flex flex-col justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Earn & Integrate
          </p>
          <h2 className="mt-2 font-heading text-2xl font-bold text-foreground">
            Auracles Partner Program
          </h2>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            Join the developer ecosystem to build third-party integrations, read framework data, embed catalog previews, and drive sales.
          </p>
          
          <ul className="mt-6 space-y-4">
            <li className="flex items-start gap-3">
              <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent text-xs font-bold">✓</span>
              <div>
                <p className="text-sm font-semibold text-foreground">Tiered Commissions</p>
                <p className="text-xs text-foreground-muted">Earn 5%, 8%, or up to 12% in commissions on every license purchase you refer.</p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent text-xs font-bold">✓</span>
              <div>
                <p className="text-sm font-semibold text-foreground">Developer APIs</p>
                <p className="text-xs text-foreground-muted">Create secure API keys with scopes tailored for catalogs, preview artifacts, or checkout.</p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent text-xs font-bold">✓</span>
              <div>
                <p className="text-sm font-semibold text-foreground">Real-Time Webhooks</p>
                <p className="text-xs text-foreground-muted">Subscribe your endpoints to signed webhook events to trigger actions instantly.</p>
              </div>
            </li>
          </ul>
        </div>

        <div className="mt-8 border-t border-border-default pt-5">
          <p className="text-xs text-foreground-muted">
            All integrations must comply with the developer terms. Minimum payout threshold is $50.00.
          </p>
        </div>
      </section>

      {/* Right side: Application form */}
      <ApplicationPanel
        applications={applications}
        latestApplication={latestApplication}
        onSubmit={onSubmit}
      />
    </div>
  );
}

/**
 * Render the Developer Platform dashboard and management controls.
 */
export function DeveloperPortal() {
  const {
    approved,
    clearRawApiKey,
    data,
    error,
    handleApiKeyCreate,
    handleApiKeyRevoke,
    handleApplicationSubmit,
    handlePayoutRequest,
    handleWebhookCreate,
    handleWebhookDelete,
    latestApplication,
    loading,
    oneTimeSecret,
    rawApiKey,
    verifiedPayoutAccounts,
  } = useDeveloperPortal();

  const [activeTab, setActiveTab] = useState<"overview" | "api" | "payouts">("overview");

  if (loading) {
    return (
      <div className="px-4 py-6 md:px-8 md:py-8 space-y-6 animate-pulse">
        <div className="h-40 rounded-2xl bg-surface-2 border border-border-default" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="h-28 rounded-2xl bg-surface-2 border border-border-default" />
          <div className="h-28 rounded-2xl bg-surface-2 border border-border-default" />
          <div className="h-28 rounded-2xl bg-surface-2 border border-border-default" />
          <div className="h-28 rounded-2xl bg-surface-2 border border-border-default" />
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 py-6 md:px-8 md:py-8 space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
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
          </div>
          {approved ? (
            <span className="w-fit rounded-badge border border-success/30 bg-success/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-success">
              Developer Account Active
            </span>
          ) : null}
        </div>
      </header>

      {error ? (
        <div className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {!approved ? (
        <DeveloperOnboarding
          applications={data.applications}
          latestApplication={latestApplication}
          onSubmit={handleApplicationSubmit}
        />
      ) : (
        <div className="space-y-6">
          {/* Tabs Navigation */}
          <div className="flex gap-2 border-b border-border-default pb-px overflow-x-auto scrollbar-none">
            <button
              onClick={() => setActiveTab("overview")}
              className={[
                "px-4 py-2.5 text-sm font-semibold border-b-2 transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent shrink-0",
                activeTab === "overview"
                  ? "border-accent text-accent"
                  : "border-transparent text-foreground-muted hover:text-foreground hover:border-border-default"
              ].join(" ")}
            >
              Overview & Performance
            </button>
            <button
              onClick={() => setActiveTab("api")}
              className={[
                "px-4 py-2.5 text-sm font-semibold border-b-2 transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent shrink-0",
                activeTab === "api"
                  ? "border-accent text-accent"
                  : "border-transparent text-foreground-muted hover:text-foreground hover:border-border-default"
              ].join(" ")}
            >
              API & Webhooks
            </button>
            <button
              onClick={() => setActiveTab("payouts")}
              className={[
                "px-4 py-2.5 text-sm font-semibold border-b-2 transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent shrink-0",
                activeTab === "payouts"
                  ? "border-accent text-accent"
                  : "border-transparent text-foreground-muted hover:text-foreground hover:border-border-default"
              ].join(" ")}
            >
              Payouts & Tier
            </button>
          </div>

          {/* Active Tab Content */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              {/* Metrics Grid */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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

              {/* Performance Analytics */}
              <AnalyticsPanel sales={data.sales} usage={data.usage} />
            </div>
          )}

          {activeTab === "api" && (
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="space-y-6">
                <ApiKeysPanel
                  apiKeys={data.apiKeys}
                  onClearRawKey={clearRawApiKey}
                  onCreate={handleApiKeyCreate}
                  onRevoke={handleApiKeyRevoke}
                  rawApiKey={rawApiKey}
                />
                <DeveloperApiUsage apiKey={rawApiKey} />
              </div>
              <WebhooksPanel
                onCreate={handleWebhookCreate}
                onDelete={handleWebhookDelete}
                oneTimeSecret={oneTimeSecret}
                webhooks={data.webhooks}
              />
            </div>
          )}

          {activeTab === "payouts" && (
            <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
              <PayoutPanel
                onRequest={handlePayoutRequest}
                payouts={data.payouts}
                verifiedAccounts={verifiedPayoutAccounts}
                sales={data.sales}
              />
              <TierPanel tier={data.tier} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
