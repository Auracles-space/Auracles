import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SavedSearchesPanel } from "@/components/modules/settings/saved-searches-panel";
import {
  deleteSavedSearch,
  listSavedSearches,
  updateSavedSearch,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  deleteSavedSearch: vi.fn(),
  listSavedSearches: vi.fn(),
  updateSavedSearch: vi.fn(),
}));

const savedSearch = {
  alert_enabled: false,
  created_at: "2026-06-11T09:00:00Z",
  filter_version: 1,
  filters: {
    category: "playbook",
    q: "risk",
    sort: "newest",
  },
  id: "search-1",
  last_alerted_at: null,
  last_alerted_framework_id: null,
  name: "Risk playbooks",
  updated_at: "2026-06-11T09:00:00Z",
  user_id: "operator-1",
};

describe("SavedSearchesPanel", () => {
  beforeEach(() => {
    vi.mocked(deleteSavedSearch).mockReset();
    vi.mocked(listSavedSearches).mockReset();
    vi.mocked(updateSavedSearch).mockReset();
  });

  it("loads saved searches and can toggle alerts", async () => {
    vi.mocked(listSavedSearches).mockResolvedValue({
      data: { saved_searches: [savedSearch] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(updateSavedSearch).mockResolvedValue({
      data: { ...savedSearch, alert_enabled: true },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<SavedSearchesPanel />);

    const row = await screen.findByRole("article", { name: /risk playbooks/i });
    expect(within(row).getByText(/playbook/i)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: /open/i })).toHaveAttribute(
      "href",
      "/explore?q=risk&category=playbook&sort=newest",
    );

    fireEvent.click(within(row).getByRole("button", { name: /enable alerts/i }));

    await waitFor(() => {
      expect(updateSavedSearch).toHaveBeenCalledWith({
        body: { alert_enabled: true },
        headers: { Authorization: "Bearer access-token" },
        path: { saved_search_id: "search-1" },
      });
    });
  });

  it("renames and deletes a saved search through generated client calls", async () => {
    vi.mocked(listSavedSearches).mockResolvedValue({
      data: { saved_searches: [savedSearch] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(updateSavedSearch).mockResolvedValue({
      data: { ...savedSearch, name: "Updated playbooks" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(deleteSavedSearch).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    });

    render(<SavedSearchesPanel />);

    const row = await screen.findByRole("article", { name: /risk playbooks/i });
    fireEvent.change(within(row).getByLabelText(/saved search name/i), {
      target: { value: "Updated playbooks" },
    });
    fireEvent.click(within(row).getByRole("button", { name: /save name/i }));

    await waitFor(() => {
      expect(updateSavedSearch).toHaveBeenCalledWith({
        body: { name: "Updated playbooks" },
        headers: { Authorization: "Bearer access-token" },
        path: { saved_search_id: "search-1" },
      });
    });

    fireEvent.click(within(row).getByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(deleteSavedSearch).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
        path: { saved_search_id: "search-1" },
      });
    });
  });
});
