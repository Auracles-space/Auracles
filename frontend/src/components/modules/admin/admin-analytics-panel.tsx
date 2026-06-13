"use client";

/**
 * Admin analytics dashboard panel.
 *
 * Loads current-state metrics and frozen daily trend rows from the admin
 * analytics endpoint and presents them in a compact operational layout.
 */
import { useEffect, useMemo, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type { AdminAnalyticsDashboardResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type MetricCardProps = {
  eyebrow: string;
  primary: string;
  secondary: string;
};

/**
 * Render one compact admin metric card.
 *
 * @param props - Headline label and values for one metric.
 */
function MetricCard({ eyebrow, primary, secondary }: MetricCardProps) {
  return (
    <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        {eyebrow}
      </p>
      <p className="mt-3 font-heading text-3xl font-bold text-foreground">{primary}</p>
      <p className="mt-2 text-sm text-foreground-muted">{secondary}</p>
    </article>
  );
}

/**
 * Format an ISO date string as a stable dashboard label.
 *
 * @param value - API snapshot date.
 */
function formatSnapshotDate(value: string): string {
  return value;
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

  const trendMax = useMemo(() => {
    const values = (dashboard?.trend ?? []).map((item) => Number(item.gmv_total));
    return Math.max(...values, 1);
  }, [dashboard?.trend]);

  if (loading) {
    return <TableSkeleton />;
  }

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
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <MetricCard
              eyebrow="GMV today"
              primary={formatMoney(dashboard.gmv.today_total)}
              secondary="Completed non-refunded USD marketplace revenue."
            />
            <MetricCard
              eyebrow="GMV last 7 days"
              primary={formatMoney(dashboard.gmv.last_7_days_total)}
              secondary="Rolling seven-day gross marketplace volume."
            />
            <MetricCard
              eyebrow="GMV last 30 days"
              primary={formatMoney(dashboard.gmv.last_30_days_total)}
              secondary="Rolling thirty-day gross marketplace volume."
            />
            <MetricCard
              eyebrow="Active users"
              primary={String(dashboard.active_users.last_24_hours)}
              secondary={`${dashboard.active_users.last_7_days} in the last 7 days`}
            />
            <MetricCard
              eyebrow="Published frameworks"
              primary={String(dashboard.frameworks_published.total)}
              secondary={`${dashboard.frameworks_published.last_30_days} new in the last 30 days`}
            />
            <MetricCard
              eyebrow="Open disputes"
              primary={String(dashboard.disputes_open.total)}
              secondary={`${dashboard.disputes_open.projects} project / ${dashboard.disputes_open.attestations} attestation`}
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
            <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                    Trend
                  </p>
                  <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
                    Frozen daily history
                  </h3>
                </div>
                <p className="text-sm text-foreground-muted">UTC snapshot rows</p>
              </div>

              <div className="mt-5 grid gap-4">
                {dashboard.trend.map((point) => (
                  <article
                    className="rounded-xl border border-border-default bg-surface-2 p-4"
                    key={point.snapshot_date}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-mono text-sm text-foreground">
                        {formatSnapshotDate(point.snapshot_date)}
                      </p>
                      <p className="text-sm font-semibold text-foreground">
                        {formatMoney(point.gmv_total)}
                      </p>
                    </div>
                    <div className="mt-3 h-2 rounded-full bg-background">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{
                          width: `${Math.max(
                            8,
                            (Number(point.gmv_total) / trendMax) * 100,
                          )}%`,
                        }}
                      />
                    </div>
                    <dl className="mt-3 grid grid-cols-2 gap-3 text-xs text-foreground-muted md:grid-cols-4">
                      <div>
                        <dt>Active</dt>
                        <dd className="mt-1 text-sm font-semibold text-foreground">
                          {point.active_users}
                        </dd>
                      </div>
                      <div>
                        <dt>Registrations</dt>
                        <dd className="mt-1 text-sm font-semibold text-foreground">
                          {point.new_registrations}
                        </dd>
                      </div>
                      <div>
                        <dt>Frameworks</dt>
                        <dd className="mt-1 text-sm font-semibold text-foreground">
                          {point.frameworks_published}
                        </dd>
                      </div>
                      <div>
                        <dt>Disputes</dt>
                        <dd className="mt-1 text-sm font-semibold text-foreground">
                          {point.disputes_open}
                        </dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                Breakdown
              </p>
              <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
                Revenue sources
              </h3>

              <div className="mt-5 grid gap-3">
                {Object.entries(dashboard.gmv.last_30_days_by_source).map(
                  ([key, value]) => (
                    <div
                      className="flex items-center justify-between rounded-xl border border-border-default bg-surface-2 px-4 py-3"
                      key={key}
                    >
                      <span className="text-sm text-foreground">
                        {formatLabel(key)}
                      </span>
                      <span className="text-sm font-semibold text-foreground">
                        {formatMoney(value)}
                      </span>
                    </div>
                  ),
                )}
              </div>
            </section>
          </div>
        </>
      ) : null}
    </section>
  );
}
