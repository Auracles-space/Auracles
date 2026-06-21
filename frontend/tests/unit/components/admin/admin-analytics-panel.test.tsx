/**
 * Unit coverage for the admin analytics panel.
 *
 * Verifies that the admin dashboard renders current metrics and frozen trend
 * rows from the generated client response.
 */
import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText("$350")).toBeInTheDocument();
    expect(screen.getByText("$775")).toBeInTheDocument();
    expect(screen.getByText("$2,075")).toBeInTheDocument();
    expect(screen.getByText("10/06/26")).toBeInTheDocument();
    expect(screen.getByText("11/06/26")).toBeInTheDocument();
    expect(screen.getByText(/framework purchase/i)).toBeInTheDocument();
    expect(screen.getByText(/open disputes/i)).toBeInTheDocument();
  });
});
