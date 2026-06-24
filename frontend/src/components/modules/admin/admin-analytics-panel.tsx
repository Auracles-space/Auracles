"use client";

/**
 * Admin analytics dashboard panel.
 *
 * Loads current-state metrics and frozen daily trend history from the admin
 * analytics endpoint and presents them in a premium dashboard layout.
 * Includes interactive SVG Doughnut charts, comparative GMV scale bar charts,
 * multi-metric snapshot trend line-area charts with tooltips, and card sparklines.
 */
import React, { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type {
  AdminAnalyticsDashboardResponse,
  AdminAnalyticsGmvBreakdown,
  AdminAnalyticsGmvResponse,
  AdminAnalyticsTrendPoint,
} from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

type MiniSparklineProps = {
  values: number[];
  colorClass?: string;
};

type MetricCardProps = {
  eyebrow: string;
  primary: string;
  secondary: string;
  sparklineValues?: number[];
  sparklineColor?: string;
};

type ChartPoint = {
  x: number;
  y: number;
};

type GMVPeriodComparisonProps = {
  today: string;
  last7: string;
  last30: string;
};

type GMVBreakdownDoughnutProps = {
  breakdown: AdminAnalyticsGmvBreakdown;
  total: string;
};

type TrendChartProps = {
  points: AdminAnalyticsTrendPoint[];
};

/**
 * Format snapshot dates as stable labels.
 */
function formatSnapshotDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year.slice(2)}`;
}

/**
 * Build line coordinates for sparklines and trends.
 */
function buildChartPoints(
  values: number[],
  width: number,
  height: number,
): ChartPoint[] {
  if (values.length === 0) {
    return [];
  }

  const maxValue = Math.max(...values, 1);
  const denominator = Math.max(values.length - 1, 1);

  return values.map((value, index) => ({
    x: (width / denominator) * index,
    y: height - (value / maxValue) * height,
  }));
}

/**
 * Convert points to SVG line path.
 */
function toLinePath(points: ChartPoint[]): string {
  if (points.length === 0) {
    return "";
  }

  return points
    .map((point, index) =>
      `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`,
    )
    .join(" ");
}

/**
 * Convert points to SVG closed gradient area path.
 */
function toAreaPath(points: ChartPoint[], height: number): string {
  if (points.length === 0) {
    return "";
  }

  const linePath = toLinePath(points);
  const lastPoint = points[points.length - 1];
  const firstPoint = points[0];

  return `${linePath} L ${lastPoint.x.toFixed(2)} ${height.toFixed(2)} L ${firstPoint.x.toFixed(2)} ${height.toFixed(2)} Z`;
}

/**
 * Sparkline component for metric cards.
 */
function MiniSparkline({ values, colorClass = "text-accent" }: MiniSparklineProps) {
  if (values.length === 0) {
    return null;
  }
  const width = 100;
  const height = 30;
  const points = buildChartPoints(values, width, height);
  const linePath = toLinePath(points);

  return (
    <svg className={`h-8 w-24 flex-shrink-0 ${colorClass}`} viewBox={`0 0 ${width} ${height}`}>
      <path
        d={linePath}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Operational metric card with micro-sparkline.
 */
function MetricCard({
  eyebrow,
  primary,
  secondary,
  sparklineValues,
  sparklineColor,
}: MetricCardProps) {
  return (
    <article className="flex items-center justify-between rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="grid gap-1">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {eyebrow}
        </p>
        <p className="mt-2 font-heading text-3xl font-bold text-foreground">{primary}</p>
        <p className="mt-1 text-sm text-foreground-muted">{secondary}</p>
      </div>
      {sparklineValues && sparklineValues.length > 0 ? (
        <div className="pl-4">
          <MiniSparkline values={sparklineValues} colorClass={sparklineColor} />
        </div>
      ) : null}
    </article>
  );
}

/**
 * Compare rolling transaction scale with an interactive bar chart.
 */
function GMVPeriodComparison({ today, last7, last30 }: GMVPeriodComparisonProps) {
  const tVal = Math.max(Number(today), 0);
  const sVal = Math.max(Number(last7), 0);
  const mVal = Math.max(Number(last30), 0);
  const maxVal = Math.max(tVal, sVal, mVal, 1);

  const items = [
    {
      label: "Today",
      value: tVal,
      formatted: formatMoney(today),
      color: "from-violet-500 to-violet-600 bg-violet-500",
    },
    {
      label: "7 Days",
      value: sVal,
      formatted: formatMoney(last7),
      color: "from-indigo-500 to-indigo-600 bg-indigo-500",
    },
    {
      label: "30 Days",
      value: mVal,
      formatted: formatMoney(last30),
      color: "from-accent to-accent/90 bg-accent",
    },
  ];

  const chartHeight = 110;

  return (
    <div className="flex flex-col h-full justify-between">
      <div className="flex items-center justify-between border-b border-border-default/40 pb-3">
        <div>
          <h4 className="text-sm font-bold text-foreground">GMV Comparative Scale</h4>
          <p className="text-xs text-foreground-muted">Comparison across primary active windows.</p>
        </div>
      </div>

      <div className="relative mt-6 flex items-end justify-around h-32 border-b border-border-default/40 pb-1">
        {/* Horizontal gridlines */}
        {[0.25, 0.5, 0.75, 1].map((pct, idx) => (
          <div
            key={idx}
            className="absolute left-0 right-0 border-t border-dashed border-border-default/10 pointer-events-none"
            style={{ bottom: `${pct * 100}%` }}
          />
        ))}

        {items.map((item) => {
          const barHeight = (item.value / maxVal) * chartHeight;
          return (
            <div key={item.label} className="group relative flex flex-col items-center w-16">
              {/* Tooltip value */}
              <div className="absolute bottom-full mb-2 opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none z-10">
                <div className="rounded-lg bg-surface-3 px-2 py-1 text-[10px] font-bold text-foreground border border-border-default shadow-md whitespace-nowrap">
                  {item.formatted}
                </div>
              </div>

              {/* Bar Rect */}
              <div
                className={`w-10 rounded-t-lg bg-gradient-to-t ${item.color} shadow-sm transition-all duration-300 group-hover:brightness-110`}
                style={{ height: `${Math.max(barHeight, 6)}px` }}
              />

              {/* Axis Label */}
              <span className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-foreground-muted">
                {item.label}
              </span>
              <span className="text-[10px] font-bold text-foreground mt-0.5">
                {item.formatted}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Premium Doughnut Breakdown for transaction sources.
 */
function GMVBreakdownDoughnut({ breakdown, total }: GMVBreakdownDoughnutProps) {
  const [activeSegment, setActiveSegment] = useState<string | null>(null);

  const segments = [
    {
      name: "framework_purchase",
      label: "Framework Purchases",
      value: Number(breakdown.framework_purchase),
      color: "text-accent",
    },
    {
      name: "collection_purchase",
      label: "Collection Purchases",
      value: Number(breakdown.collection_purchase),
      color: "text-indigo-500",
    },
    {
      name: "project_milestone",
      label: "Project Milestones",
      value: Number(breakdown.project_milestone),
      color: "text-violet-500",
    },
    {
      name: "attestation_fee",
      label: "Attestation Fees",
      value: Number(breakdown.attestation_fee),
      color: "text-teal-500",
    },
  ];

  const totalVal = segments.reduce((sum, seg) => sum + seg.value, 0);
  const r = 50;
  const C = 2 * Math.PI * r; // 314.159

  let accumulatedOffset = 0;
  const strokeSegments = segments.map((seg) => {
    const share = totalVal > 0 ? seg.value / totalVal : 0;
    const strokeLength = share * C;
    const strokeOffset = accumulatedOffset;
    accumulatedOffset += strokeLength;
    return {
      ...seg,
      strokeLength,
      strokeOffset: -strokeOffset,
      share,
    };
  });

  const hoveredSegment = segments.find((seg) => seg.name === activeSegment) ?? null;

  return (
    <div className="flex flex-col items-center justify-center gap-6 sm:flex-row">
      <div className="relative h-40 w-40 flex-shrink-0">
        <svg className="h-full w-full" viewBox="0 0 160 160">
          {/* Background circle */}
          <circle
            className="text-border-default/10"
            cx="80"
            cy="80"
            fill="transparent"
            r="50"
            stroke="currentColor"
            strokeWidth="10"
          />
          {strokeSegments.map((seg) => (
            <circle
              key={seg.name}
              className={`${seg.color} transition-all duration-200 cursor-pointer`}
              cx="80"
              cy="80"
              fill="transparent"
              r="50"
              stroke="currentColor"
              strokeDasharray={`${seg.strokeLength} ${C}`}
              strokeDashoffset={seg.strokeOffset}
              strokeWidth={activeSegment === seg.name ? "14" : "10"}
              style={{ transform: "rotate(-90deg)", transformOrigin: "80px 80px" }}
              onMouseEnter={() => setActiveSegment(seg.name)}
              onMouseLeave={() => setActiveSegment(null)}
            />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none select-none text-center p-2">
          <p className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-muted truncate max-w-[110px]">
            {hoveredSegment ? hoveredSegment.label : "Total GMV"}
          </p>
          <p className="mt-1 font-heading text-lg font-bold text-foreground">
            {hoveredSegment
              ? formatMoney(String(hoveredSegment.value))
              : formatMoney(total)}
          </p>
        </div>
      </div>

      <div className="grid gap-2 w-full">
        {strokeSegments.map((seg) => {
          const sharePct = seg.share * 100;
          return (
            <article
              key={seg.name}
              className={`flex items-center justify-between rounded-xl border p-2 text-xs transition-colors ${
                activeSegment === seg.name
                  ? "border-border-default bg-surface-3"
                  : "border-transparent bg-surface-2"
              }`}
              onMouseEnter={() => setActiveSegment(seg.name)}
              onMouseLeave={() => setActiveSegment(null)}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${seg.color.replace("text-", "bg-")}`}
                />
                <span className="font-semibold text-foreground">{seg.label}</span>
              </div>
              <div className="text-right">
                <span className="font-semibold text-foreground">
                  {formatMoney(String(seg.value))}
                </span>
                <span className="ml-1.5 text-[10px] text-foreground-muted font-bold">
                  {sharePct.toFixed(1)}%
                </span>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Cohesive Gross Marketplace Volume dashboard section containing charts.
 */
function GMVOverviewSection({ gmv }: { gmv: AdminAnalyticsGmvResponse }) {
  const [activeTab, setActiveTab] = useState<"today" | "7days" | "30days">("30days");

  const currentBreakdown =
    activeTab === "today"
      ? gmv.today_by_source
      : activeTab === "7days"
        ? gmv.last_7_days_by_source
        : gmv.last_30_days_by_source;

  const currentTotal =
    activeTab === "today"
      ? gmv.today_total
      : activeTab === "7days"
        ? gmv.last_7_days_total
        : gmv.last_30_days_total;

  return (
    <section className="grid gap-6 lg:grid-cols-2">
      {/* Volume Comparison and Bar Chart */}
      <article className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm flex flex-col justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Volume Comparison
          </p>
          <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
            Marketplace GMV Overview
          </h3>
          <p className="mt-2 text-sm text-foreground-muted mb-6">
            Compare transaction scale across active rolling periods.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-3 mb-6">
          <div className="rounded-xl border border-border-default bg-surface-2 p-3 text-center">
            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted">
              Today
            </p>
            <p className="mt-1.5 font-heading text-lg font-bold text-foreground">
              {formatMoney(gmv.today_total)}
            </p>
          </div>
          <div className="rounded-xl border border-border-default bg-surface-2 p-3 text-center">
            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted">
              7 Days
            </p>
            <p className="mt-1.5 font-heading text-lg font-bold text-foreground">
              {formatMoney(gmv.last_7_days_total)}
            </p>
          </div>
          <div className="rounded-xl border border-border-default bg-surface-2 p-3 text-center">
            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-muted">
              30 Days
            </p>
            <p className="mt-1.5 font-heading text-lg font-bold text-foreground">
              {formatMoney(gmv.last_30_days_total)}
            </p>
          </div>
        </div>

        <GMVPeriodComparison
          last7={gmv.last_7_days_total}
          last30={gmv.last_30_days_total}
          today={gmv.today_total}
        />
      </article>

      {/* Doughnut Breakdown Card */}
      <article className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm flex flex-col justify-between">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                Breakdown
              </p>
              <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
                Revenue Mix
              </h3>
            </div>
            <div className="flex rounded-lg bg-surface-2 p-1 border border-border-default select-none">
              {(["today", "7days", "30days"] as const).map((tab) => (
                <button
                  key={tab}
                  className={`rounded-md px-2.5 py-1 text-xs font-semibold uppercase tracking-wider outline-none transition-all ${
                    activeTab === tab
                      ? "bg-foreground text-background shadow-sm"
                      : "text-foreground-muted hover:text-foreground"
                  }`}
                  onClick={() => setActiveTab(tab)}
                  type="button"
                >
                  {tab === "today" ? "Today" : tab === "7days" ? "7D" : "30D"}
                </button>
              ))}
            </div>
          </div>
          <p className="text-sm text-foreground-muted mb-6">
            Gross marketplace volume distributed by transaction type.
          </p>
        </div>

        <GMVBreakdownDoughnut breakdown={currentBreakdown} total={currentTotal} />
      </article>
    </section>
  );
}

/**
 * Interactive Line/Area Chart for snapshot trends.
 */
function TrendChart({ points }: TrendChartProps) {
  const [activeMetric, setActiveMetric] = useState<
    "gmv" | "users" | "registrations" | "frameworks" | "disputes"
  >("gmv");
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const metricsConfig = {
    gmv: {
      accessor: (p: AdminAnalyticsTrendPoint) => Number(p.gmv_total),
      colorClass: "text-accent",
      formatter: (v: number) => formatMoney(String(v)),
      gradientId: "gmvGradient",
      label: "GMV",
    },
    users: {
      accessor: (p: AdminAnalyticsTrendPoint) => p.active_users,
      colorClass: "text-indigo-500",
      formatter: (v: number) => String(v),
      gradientId: "usersGradient",
      label: "Active Users",
    },
    registrations: {
      accessor: (p: AdminAnalyticsTrendPoint) => p.new_registrations,
      colorClass: "text-violet-500",
      formatter: (v: number) => String(v),
      gradientId: "registrationsGradient",
      label: "Registrations",
    },
    frameworks: {
      accessor: (p: AdminAnalyticsTrendPoint) => p.frameworks_published,
      colorClass: "text-teal-500",
      formatter: (v: number) => String(v),
      gradientId: "frameworksGradient",
      label: "Published Frameworks",
    },
    disputes: {
      accessor: (p: AdminAnalyticsTrendPoint) => p.disputes_open,
      colorClass: "text-error",
      formatter: (v: number) => String(v),
      gradientId: "disputesGradient",
      label: "Open Disputes",
    },
  };

  const chartWidth = 640;
  const chartHeight = 220;
  const config = metricsConfig[activeMetric];
  const values = points.map(config.accessor);
  const chartPoints = buildChartPoints(values, chartWidth, chartHeight);

  const handleMouseMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const svg = event.currentTarget;
    const rect = svg.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const pctX = mouseX / rect.width;
    const innerX = pctX * chartWidth;
    const stepWidth = chartWidth / Math.max(points.length - 1, 1);
    const index = Math.round(innerX / stepWidth);
    if (index >= 0 && index < points.length) {
      setHoveredIndex(index);
    }
  };

  const handleMouseLeave = () => {
    setHoveredIndex(null);
  };

  const hoveredPoint = hoveredIndex !== null ? points[hoveredIndex] : null;
  const hoveredCoord = hoveredIndex !== null ? chartPoints[hoveredIndex] : null;

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm relative">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between mb-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Snapshot Trends
          </p>
          <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
            Platform Snapshot History
          </h3>
          <p className="mt-2 text-sm text-foreground-muted">
            Frozen daily UTC metrics across checkpoints. Select a metric to visualize.
          </p>
        </div>

        {/* Metric Switcher pills */}
        <div className="flex flex-wrap gap-1.5 rounded-lg bg-surface-2 p-1 border border-border-default self-start select-none">
          {(
            Object.keys(metricsConfig) as Array<keyof typeof metricsConfig>
          ).map((key) => (
            <button
              key={key}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeMetric === key
                  ? "bg-foreground text-background shadow-sm"
                  : "text-foreground-muted hover:text-foreground"
              }`}
              onClick={() => setActiveMetric(key)}
              type="button"
            >
              {metricsConfig[key].label}
            </button>
          ))}
        </div>
      </div>

      {points.length > 0 ? (
        <div className="relative">
          <div className="overflow-hidden rounded-xl border border-border-default bg-surface-2 p-4">
            <svg
              aria-label="Platform metric trend chart"
              className="h-64 w-full cursor-crosshair"
              role="img"
              viewBox={`0 0 ${chartWidth} ${chartHeight}`}
              onMouseMove={handleMouseMove}
              onMouseLeave={handleMouseLeave}
            >
              <defs>
                <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    className={config.colorClass}
                    offset="0%"
                    stopColor="currentColor"
                    stopOpacity="0.2"
                  />
                  <stop
                    className={config.colorClass}
                    offset="100%"
                    stopColor="currentColor"
                    stopOpacity="0.0"
                  />
                </linearGradient>
              </defs>

              {/* Gridlines */}
              {[0, 1, 2, 3].map((step) => {
                const y = (chartHeight / 3) * step;
                return (
                  <line
                    key={step}
                    stroke="currentColor"
                    strokeDasharray="6 6"
                    strokeOpacity="0.14"
                    strokeWidth="1"
                    x1="0"
                    x2={chartWidth}
                    y1={y}
                    y2={y}
                  />
                );
              })}

              {/* Area path */}
              <path d={toAreaPath(chartPoints, chartHeight)} fill="url(#trendGradient)" />

              {/* Line path */}
              <path
                className={config.colorClass}
                d={toLinePath(chartPoints)}
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="3.5"
              />

              {/* Interactive cursor line */}
              {hoveredCoord ? (
                <line
                  className="text-foreground-muted/30"
                  stroke="currentColor"
                  strokeDasharray="4 4"
                  strokeWidth="1.5"
                  x1={hoveredCoord.x}
                  x2={hoveredCoord.x}
                  y1={0}
                  y2={chartHeight}
                />
              ) : null}

              {/* Data points circles */}
              {chartPoints.map((point, index) => (
                <circle
                  key={points[index].snapshot_date}
                  className={`${config.colorClass} transition-all duration-150`}
                  cx={point.x}
                  cy={point.y}
                  fill="currentColor"
                  r={hoveredIndex === index ? "6.5" : "3.5"}
                  stroke={hoveredIndex === index ? "#ffffff" : "none"}
                  strokeWidth={hoveredIndex === index ? 2 : 0}
                />
              ))}
            </svg>

            {/* X Axis Dates */}
            <div className="mt-4 flex justify-between text-[10px] font-semibold text-foreground-muted px-2 select-none">
              <span>{formatSnapshotDate(points[0].snapshot_date)}</span>
              {points.length > 2 ? (
                <span>
                  {formatSnapshotDate(
                    points[Math.floor(points.length / 2)].snapshot_date,
                  )}
                </span>
              ) : null}
              <span>{formatSnapshotDate(points[points.length - 1].snapshot_date)}</span>
            </div>
          </div>

          {/* Interactive Tooltip Card */}
          {hoveredPoint && hoveredCoord ? (
            <div
              className="absolute pointer-events-none z-20 rounded-xl border border-border-default bg-surface-2/95 backdrop-blur-md p-3 shadow-lg flex flex-col gap-1 transition-all duration-100 ease-out"
              style={{
                left: `${(hoveredCoord.x / chartWidth) * 100}%`,
                marginTop: "-12px",
                top: `${(hoveredCoord.y / chartHeight) * 100}%`,
                transform: "translate(-50%, -100%)",
              }}
            >
              <span className="text-[9px] font-bold uppercase tracking-wider text-foreground-muted">
                {formatSnapshotDate(hoveredPoint.snapshot_date)}
              </span>
              <div className="flex items-center gap-2">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${config.colorClass.replace("text-", "bg-")}`}
                />
                <span className="text-xs font-semibold text-foreground">
                  {config.label}
                </span>
                <span className="text-xs font-bold text-foreground ml-auto">
                  {config.formatter(config.accessor(hoveredPoint))}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-6 rounded-xl border border-dashed border-border-default bg-surface-2 p-6 text-sm text-foreground-muted">
          No snapshot data available.
        </div>
      )}
    </section>
  );
}

/**
 * Render the admin analytics workspace.
 */
export function AdminAnalyticsPanel() {
  const [dashboard, setDashboard] = useState<AdminAnalyticsDashboardResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function loadDashboard(): Promise<void> {
      configureBrowserClient();
      const result = await getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet({
        headers: getAccessTokenHeaders(),
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
      setDashboard(result.data);
    }

    void loadDashboard();
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return <TableSkeleton />;
  }

  // Generate mock history when the real series is sparse, but ONLY in local
  // development. Never fabricate analytics in production (or tests) — an admin
  // reporting dashboard must show real snapshot data, even when there are few
  // points yet.
  let trend = dashboard?.trend ?? [];
  if (
    process.env.NODE_ENV === "development" &&
    dashboard &&
    trend.length < 3
  ) {
    const mockPoints: AdminAnalyticsTrendPoint[] = [];
    const oldestPoint = trend[0] ?? {
      active_users: 12,
      attestations_issued: 2,
      disputes_open: 1,
      frameworks_published: 8,
      gmv_total: "350.00",
      new_registrations: 3,
      snapshot_date: new Date().toISOString().split("T")[0],
    };

    const baseDate = new Date(oldestPoint.snapshot_date);

    for (let i = 5; i >= 0; i--) {
      const date = new Date(baseDate);
      date.setDate(baseDate.getDate() - (i + 1));
      const dateStr = date.toISOString().split("T")[0];

      const gmvVal = 100 + i * 80 + Math.sin(i) * 50;
      const usersVal = 15 + i * 6 + Math.cos(i) * 3;
      const regVal = 2 + (i % 3) * 2;
      const fwVal = 3 + Math.floor(i / 2) * 2;
      const dispVal = (i + 1) % 2;

      mockPoints.push({
        snapshot_date: dateStr,
        gmv_total: String(gmvVal.toFixed(2)),
        active_users: usersVal,
        new_registrations: regVal,
        frameworks_published: fwVal,
        attestations_issued: i % 2,
        disputes_open: dispVal,
      });
    }

    mockPoints.push(...trend);
    trend = mockPoints;
  }

  const activeUsersTrend = trend.map((p) => p.active_users);
  const frameworksTrend = trend.map((p) => p.frameworks_published);
  const disputesTrend = trend.map((p) => p.disputes_open);

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin analytics
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Platform analytics
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Inspect live marketplace totals and compare them against the frozen UTC
          daily trend history that powers reporting.
        </p>
      </header>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {dashboard ? (
        <>
          {/* GMV/Financials Overview Section */}
          <GMVOverviewSection gmv={dashboard.gmv} />

          {/* Operational Metrics Cards with Sparklines */}
          <div className="grid gap-4 md:grid-cols-3">
            <MetricCard
              eyebrow="Active users"
              primary={String(dashboard.active_users.last_24_hours)}
              secondary={`${dashboard.active_users.last_7_days} in the last 7 days`}
              sparklineColor="text-indigo-500"
              sparklineValues={activeUsersTrend}
            />
            <MetricCard
              eyebrow="Published frameworks"
              primary={String(dashboard.frameworks_published.total)}
              secondary={`${dashboard.frameworks_published.last_30_days} new in the last 30 days`}
              sparklineColor="text-teal-500"
              sparklineValues={frameworksTrend}
            />
            <MetricCard
              eyebrow="Open disputes"
              primary={String(dashboard.disputes_open.total)}
              secondary={`${dashboard.disputes_open.projects} project / ${dashboard.disputes_open.attestations} attestation`}
              sparklineColor="text-error"
              sparklineValues={disputesTrend}
            />
          </div>

          {/* Fully Interactive Multi-Metric Trend Chart */}
          <TrendChart points={trend} />
        </>
      ) : null}
    </section>
  );
}
