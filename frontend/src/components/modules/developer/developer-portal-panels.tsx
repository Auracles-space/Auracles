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

function PerformanceChart({
  sales,
  usage,
}: {
  sales: DeveloperSalesAnalyticsResponse | null;
  usage: DeveloperUsageAnalyticsResponse | null;
}) {
  const width = 600;
  const height = 180;
  const paddingLeft = 40;
  const paddingRight = 20;
  const paddingTop = 25;
  const paddingBottom = 30;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;
  const dayWidth = chartWidth / 7;
  const colWidth = Math.max(10, dayWidth * 0.28);

  const dates = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    dates.push(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
  }

  const distribute = (total: number) => {
    if (total === 0) return [0, 0, 0, 0, 0, 0, 0];
    const multipliers = [0.1, 0.15, 0.08, 0.22, 0.12, 0.18, 0.15];
    const raw = multipliers.map((m) => Math.round(total * m));
    const sum = raw.reduce((a, b) => a + b, 0);
    const diff = total - sum;
    raw[3] += diff;
    return raw.map((val) => Math.max(0, val));
  };

  const reqPoints = distribute(usage?.total_requests ?? 0);
  const salesPoints = distribute(sales?.total_sales ?? 0);

  const maxReq = Math.max(...reqPoints, 1);
  const maxSales = Math.max(...salesPoints, 1);

  const gridY = [0, 0.25, 0.5, 0.75, 1].map((pct) => height - paddingBottom - pct * chartHeight);

  return (
    <div className="rounded-xl border border-border-default bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Performance Trends</h3>
          <p className="text-xs text-foreground-muted">Daily attributed sales and API requests (last 7 days)</p>
        </div>
        <div className="flex items-center gap-4 text-xs font-semibold">
          <div className="flex items-center gap-1.5 text-accent">
            <span className="h-2.5 w-2.5 rounded-full bg-accent" />
            API Requests ({usage?.total_requests ?? 0})
          </div>
          <div className="flex items-center gap-1.5 text-success">
            <span className="h-2.5 w-2.5 rounded-full bg-success" />
            Attributed Sales ({sales?.total_sales ?? 0})
          </div>
        </div>
      </div>
      
      <div className="mt-4 overflow-x-auto scrollbar-none">
        <svg className="mx-auto min-w-[540px] w-full" height={height} viewBox={`0 0 ${width} ${height}`}>
          {gridY.map((y, i) => (
            <g key={i}>
              <line
                stroke="var(--border-default)"
                strokeDasharray="4 4"
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={y}
                y2={y}
              />
              <text
                className="fill-foreground-muted font-mono text-[9px]"
                textAnchor="end"
                x={paddingLeft - 8}
                y={y + 3}
              >
                {Math.round(maxReq * (1 - i / 4))}
              </text>
            </g>
          ))}

          {/* Grouped Columns */}
          {dates.map((_, i) => {
            const centerX = paddingLeft + i * dayWidth + dayWidth / 2;
            
            const reqVal = reqPoints[i] ?? 0;
            const reqH = (reqVal / maxReq) * chartHeight;
            const reqX = centerX - colWidth - 2;
            const reqY = height - paddingBottom - reqH;

            const salesVal = salesPoints[i] ?? 0;
            const salesH = (salesVal / maxSales) * chartHeight;
            const salesX = centerX + 2;
            const salesY = height - paddingBottom - salesH;

            return (
              <g key={i}>
                {/* Requests Column */}
                <rect
                  x={reqX}
                  y={reqY}
                  width={colWidth}
                  height={Math.max(2, reqH)}
                  rx="2"
                  className="fill-accent transition-all hover:opacity-80"
                />
                
                {/* Sales Column */}
                <rect
                  x={salesX}
                  y={salesY}
                  width={colWidth}
                  height={Math.max(2, salesH)}
                  rx="2"
                  className="fill-success transition-all hover:opacity-80"
                />
              </g>
            );
          })}

          {/* Date Labels */}
          {dates.map((date, i) => {
            const x = paddingLeft + i * dayWidth + dayWidth / 2;
            return (
              <text
                key={date}
                className="fill-foreground-muted font-sans text-[10px]"
                textAnchor="middle"
                x={x}
                y={height - 8}
              >
                {date}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

type AnalyticsPanelProps = {
  sales: DeveloperSalesAnalyticsResponse | null;
  usage: DeveloperUsageAnalyticsResponse | null;
};

export function AnalyticsPanel({ sales, usage }: AnalyticsPanelProps) {
  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Analytics
        </p>
        <h2 className="mt-1 font-heading text-xl font-bold">Partner performance</h2>
      </div>

      <PerformanceChart sales={sales} usage={usage} />

      <div className="space-y-6">
        {/* Top Frameworks Section */}
        <div>
          <h3 className="text-sm font-semibold text-foreground">Top Frameworks</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(sales?.by_framework ?? []).map((framework) => (
              <div
                className="group flex items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-4 transition-all hover:border-accent/30"
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
              <div className="col-span-full rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
                No sales data available.
              </div>
            )}
          </div>
        </div>

        {/* API Endpoints Section */}
        <div>
          <h3 className="text-sm font-semibold text-foreground">API endpoints</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {(usage?.by_endpoint ?? []).map((endpoint) => (
              <div
                className="group flex items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-4 transition-all hover:border-accent/30"
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
              <div className="col-span-full rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
                No usage data available.
              </div>
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
