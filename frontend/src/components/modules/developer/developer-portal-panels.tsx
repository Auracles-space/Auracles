"use client";

/**
 * Developer portal display panels.
 *
 * Contains compact, read-only Partner Developer cards for metrics, analytics,
 * and commission tier progress.
 */

import type {
  DeveloperSalesAnalyticsResponse,
  DeveloperTierProgressResponse,
  DeveloperUsageAnalyticsResponse,
} from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

type MetricCardProps = {
  helper: string;
  label: string;
  value: string;
};

/**
 * Render one Developer dashboard metric card.
 *
 * @param props - Metric label, headline value, and secondary helper text.
 */
export function MetricCard({ helper, label, value }: MetricCardProps) {
  return (
    <article className="group relative overflow-hidden rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm transition-all hover:border-accent/50 hover:shadow-[0_4px_12px_rgba(0,0,0,0.05)]">
      <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-accent/5 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      <p className="relative z-10 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        {label}
      </p>
      <p className="relative z-10 mt-3 font-heading text-3xl font-bold text-foreground">
        {value}
      </p>
      <p className="relative z-10 mt-1 text-sm text-foreground-muted">{helper}</p>
    </article>
  );
}

type AnalyticsPanelProps = {
  sales: DeveloperSalesAnalyticsResponse | null;
  usage: DeveloperUsageAnalyticsResponse | null;
};

/**
 * Render Partner sales and API usage breakdowns.
 *
 * @param props - Aggregate sales and usage analytics.
 */
export function AnalyticsPanel({ sales, usage }: AnalyticsPanelProps) {
  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Analytics
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Partner performance</h2>
      <div className="mt-5 grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Top Frameworks</h3>
          <div className="mt-3 overflow-hidden rounded-xl border border-border-default bg-surface-2">
            {(sales?.by_framework ?? []).map((framework, index) => (
              <div
                className={`group flex items-center justify-between gap-3 p-4 transition-colors hover:bg-surface-1 ${
                  index !== 0 ? "border-t border-border-default" : ""
                }`}
                key={framework.framework_id}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold transition-colors group-hover:text-accent">
                    {framework.framework_title}
                  </p>
                  <p className="text-xs text-foreground-muted">
                    {framework.sale_count} sales
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="font-heading text-sm font-bold text-foreground">
                    {formatMoney(framework.commission_amount)}
                  </p>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-accent">
                    Commission
                  </p>
                </div>
              </div>
            ))}
            {(sales?.by_framework ?? []).length === 0 && (
              <div className="p-4 text-sm text-foreground-muted">No sales data available.</div>
            )}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-foreground">API endpoints</h3>
          <div className="mt-3 overflow-hidden rounded-xl border border-border-default bg-surface-2">
            {(usage?.by_endpoint ?? []).map((endpoint, index) => (
              <div
                className={`group flex items-center justify-between gap-3 p-4 transition-colors hover:bg-surface-1 ${
                  index !== 0 ? "border-t border-border-default" : ""
                }`}
                key={`${endpoint.method}:${endpoint.endpoint}`}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold transition-colors group-hover:text-accent">
                    {endpoint.endpoint}
                  </p>
                  <p className="mt-1 w-fit rounded border border-border-default bg-background px-1.5 py-0.5 font-mono text-[10px] font-medium text-foreground-muted">
                    {endpoint.method}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="font-heading text-sm font-bold text-foreground">
                    {endpoint.request_count} reqs
                  </p>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-foreground-muted">
                    {endpoint.average_response_ms}ms avg
                  </p>
                </div>
              </div>
            ))}
            {(usage?.by_endpoint ?? []).length === 0 && (
              <div className="p-4 text-sm text-foreground-muted">No usage data available.</div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

type TierPanelProps = {
  tier: DeveloperTierProgressResponse | null;
};

/**
 * Render Partner tier progress.
 *
 * @param props - Current tier progress from the Developer API.
 */
export function TierPanel({ tier }: TierPanelProps) {
  return (
    <section className="relative overflow-hidden rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <div className="absolute right-0 top-0 h-32 w-32 -translate-y-1/2 translate-x-1/2 rounded-full bg-accent/10 blur-2xl" />
      <p className="relative z-10 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Tier Progress
      </p>
      <div className="relative z-10 mt-4 flex items-end gap-3">
        <h2 className="font-heading text-4xl font-bold text-foreground">
          Tier {tier?.current_tier ?? 1}
        </h2>
        <span className="mb-1 rounded-md border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.05em] text-accent">
          Active
        </span>
      </div>
      
      <div className="relative z-10 mt-6 grid gap-4 border-t border-border-default pt-5">
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-foreground-muted">Last 30 days</span>
            <span className="font-semibold text-foreground">{tier?.prior_30d_sales_count ?? 0} sales</span>
          </div>
        </div>
        
        <div>
          <div className="mb-2 flex justify-between text-sm">
            <span className="text-foreground-muted">Next Tier</span>
            <span className="font-semibold text-foreground">{tier?.next_tier_sales_required ?? 0} needed</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
            <div 
              className="h-full rounded-full bg-accent transition-all duration-1000 ease-out" 
              style={{ 
                width: `${Math.min(100, Math.max(0, ((tier?.prior_30d_sales_count ?? 0) / ((tier?.prior_30d_sales_count ?? 0) + (tier?.next_tier_sales_required ?? 1))) * 100))}%` 
              }} 
            />
          </div>
        </div>
      </div>
    </section>
  );
}
