import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ExploreSaveSearchAction,
  filtersFromExploreSearchParams,
} from "@/components/modules/explore/save-search-action";
import { createSavedSearch } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createSavedSearch: vi.fn(),
}));

describe("ExploreSaveSearchAction", () => {
  beforeEach(() => {
    vi.mocked(createSavedSearch).mockReset();
  });

  it("builds saved-search filters from the current Explore query string", () => {
    const filters = filtersFromExploreSearchParams({
      category: "playbook",
      page: "3",
      q: "risk register",
      sector: "healthcare",
      sort: "top-rated",
    });

    expect(filters).toEqual({
      category: "playbook",
      q: "risk register",
      sector: "healthcare",
      sort: "top-rated",
    });
  });

  it("saves the current filters through the generated client", async () => {
    vi.mocked(createSavedSearch).mockResolvedValue({
      data: {
        alert_enabled: false,
        created_at: "2026-06-11T09:00:00Z",
        filter_version: 1,
        filters: { category: "playbook", q: "risk", sort: "newest" },
        id: "search-1",
        last_alerted_at: null,
        last_alerted_framework_id: null,
        name: "Risk watch",
        updated_at: "2026-06-11T09:00:00Z",
        user_id: "operator-1",
      },
      error: undefined,
      response: new Response(null, { status: 201 }),
    });

    render(
      <ExploreSaveSearchAction
        filters={{ category: "playbook", q: "risk", sort: "newest" }}
      />,
    );

    fireEvent.change(screen.getByLabelText(/saved search name/i), {
      target: { value: "Risk watch" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save search/i }));

    await waitFor(() => {
      expect(createSavedSearch).toHaveBeenCalledWith({
        body: {
          alert_enabled: false,
          filters: { category: "playbook", q: "risk", sort: "newest" },
          name: "Risk watch",
        },
        headers: { Authorization: "Bearer access-token" },
      });
    });
    expect(await screen.findByText(/saved as risk watch/i)).toBeInTheDocument();
  });
});
