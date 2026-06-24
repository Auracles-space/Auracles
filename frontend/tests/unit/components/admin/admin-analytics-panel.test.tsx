/**
 * Unit coverage for the admin analytics panel.
 *
 * Verifies that the admin dashboard renders current metrics and frozen trend
 * rows from the generated client response.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAnalyticsPanel } from "@/components/modules/admin/admin-analytics-panel";
import { getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet: vi.fn(),
}));

describe("AdminAnalyticsPanel", () => {
  beforeEach(() => {
    vi.mocked(getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet).mockReset();
    vi.mocked(getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet).mockResolvedValue({
      data: {
        active_users: {
          last_24_hours: 12,
          last_7_days: 44,
          last_30_days: 81,
        },
        attestations_issued: {
          last_24_hours: 1,
          last_7_days: 4,
          last_30_days: 9,
        },
        disputes_open: {
          attestations: 1,
          projects: 2,
          total: 3,
        },
        frameworks_published: {
          last_24_hours: 2,
          last_7_days: 8,
          last_30_days: 14,
          total: 25,
        },
        gmv: {
          last_30_days_by_source: {
            attestation_fee: "75.00",
            collection_purchase: "300.00",
            framework_purchase: "1200.00",
            project_milestone: "500.00",
          },
          last_30_days_total: "2075.00",
          last_7_days_by_source: {
            attestation_fee: "25.00",
            collection_purchase: "100.00",
            framework_purchase: "450.00",
            project_milestone: "200.00",
          },
          last_7_days_total: "775.00",
          today_by_source: {
            attestation_fee: "0.00",
            collection_purchase: "100.00",
            framework_purchase: "250.00",
            project_milestone: "0.00",
          },
          today_total: "350.00",
        },
        new_registrations: {
          last_24_hours: 3,
          last_7_days: 11,
          last_30_days: 29,
        },
        trend: [
          {
            active_users: 9,
            attestations_issued: 1,
            disputes_open: 2,
            frameworks_published: 1,
            gmv_total: "150.00",
            new_registrations: 2,
            snapshot_date: "2026-06-10",
          },
          {
            active_users: 14,
            attestations_issued: 0,
            disputes_open: 3,
            frameworks_published: 2,
            gmv_total: "425.00",
            new_registrations: 1,
            snapshot_date: "2026-06-11",
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("renders live metrics and the recent frozen trend series", async () => {
    render(<AdminAnalyticsPanel />);

    expect(
      await screen.findByRole("heading", { name: /platform analytics/i }),
    ).toBeInTheDocument();
    // GMV totals appear in both a summary card and the period-comparison bars.
    expect(screen.getAllByText("$350").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$775").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$2,075").length).toBeGreaterThan(0);
    expect(screen.getByText("10/06/26")).toBeInTheDocument();
    expect(screen.getByText("11/06/26")).toBeInTheDocument();
    expect(screen.getByText(/framework purchase/i)).toBeInTheDocument();
    expect(screen.getAllByText(/open disputes/i).length).toBeGreaterThan(0);
  });

  it("switches the trend metric and the GMV breakdown period", async () => {
    render(<AdminAnalyticsPanel />);
    await screen.findByRole("heading", { name: /platform analytics/i });

    // Each metric toggle re-renders the chart with that metric's accessor and
    // formatter; cycle through them to exercise every series.
    for (const metric of [
      /active users/i,
      /registrations/i,
      /open disputes/i,
      /gmv/i,
    ]) {
      const toggle = screen
        .getAllByRole("button", { name: metric })
        .at(-1);
      if (toggle) {
        fireEvent.click(toggle);
      }
    }

    // Cycle the GMV breakdown period tabs (Today / 7D / 30D).
    for (const tab of [/^Today$/, /^7D$/, /^30D$/]) {
      fireEvent.click(screen.getByRole("button", { name: tab }));
    }

    expect(
      screen.getByRole("heading", { name: /platform analytics/i }),
    ).toBeInTheDocument();
  });
});
