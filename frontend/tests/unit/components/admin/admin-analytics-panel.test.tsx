/**
 * Tests for the admin analytics panel.
 *
 * Staging has no frozen snapshot history yet, so the dashboard arrives with an
 * empty `trend`. The panel must render that, not crash the route.
 */
import { render, screen, waitFor } from "@testing-library/react";
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

/** The exact payload staging returns today: real zeros, empty trend. */
const STAGING_PAYLOAD = {
  active_users: { last_24_hours: 4, last_7_days: 4, last_30_days: 4 },
  attestations_issued: { last_24_hours: 0, last_7_days: 0, last_30_days: 0 },
  disputes_open: { attestations: 0, projects: 0, total: 0 },
  frameworks_published: {
    last_24_hours: 0,
    last_7_days: 0,
    last_30_days: 0,
    total: 0,
  },
  gmv: {
    last_7_days_by_source: {
      attestation_fee: "0.00",
      collection_purchase: "0.00",
      framework_purchase: "0.00",
      project_milestone: "0.00",
    },
    last_7_days_total: "0.00",
    last_30_days_by_source: {
      attestation_fee: "0.00",
      collection_purchase: "0.00",
      framework_purchase: "0.00",
      project_milestone: "0.00",
    },
    last_30_days_total: "0.00",
    today_by_source: {
      attestation_fee: "0.00",
      collection_purchase: "0.00",
      framework_purchase: "0.00",
      project_milestone: "0.00",
    },
    today_total: "0.00",
  },
  new_registrations: { last_24_hours: 4, last_7_days: 4, last_30_days: 4 },
  trend: [],
};

describe("AdminAnalyticsPanel", () => {
  beforeEach(() => {
    vi.mocked(
      getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet,
    ).mockReset();
  });

  it("renders a dashboard whose snapshot history is empty", async () => {
    // Reproduces staging: no snapshots have been frozen yet, so `trend` is [].
    vi.mocked(
      getAdminAnalyticsDashboardV1AdminAnalyticsDashboardGet,
    ).mockResolvedValue({
      data: STAGING_PAYLOAD,
      error: undefined,
      request: new Request("http://127.0.0.1:8000"),
      response: new Response(null, { status: 200 }),
    });

    render(<AdminAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/no snapshot data available/i)).toBeInTheDocument();
    });
  });
});
