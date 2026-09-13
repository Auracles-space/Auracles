/**
 * Unit coverage for the admin Framework directory panel.
 *
 * Verifies the published-Framework list renders with owner and timestamp,
 * search narrows the query, delisting drops the row, a failed delist surfaces
 * an error and keeps the row, and the empty state shows when nothing matches.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFrameworkDirectoryPanel } from "@/components/modules/admin/admin-framework-directory-panel";
import {
  listAdminFrameworksV1AdminFrameworksGet,
  suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminFrameworksV1AdminFrameworksGet: vi.fn(),
  suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

const publishedItem = {
  framework_id: "framework-1",
  title: "Governance Operating Model",
  contributor_id: "contributor-1",
  contributor_name: "Ada Contributor",
  status: "published",
  published_at: "2026-06-20T10:00:00Z",
};

describe("AdminFrameworkDirectoryPanel", () => {
  beforeEach(() => {
    vi.mocked(listAdminFrameworksV1AdminFrameworksGet).mockReset();
    vi.mocked(suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost).mockReset();
    vi.mocked(listAdminFrameworksV1AdminFrameworksGet).mockResolvedValue(
      ok({ items: [publishedItem] }),
    );
  });

  it("lists published frameworks with owner and publish date", async () => {
    render(<AdminFrameworkDirectoryPanel />);

    expect(
      await screen.findByText("Governance Operating Model"),
    ).toBeInTheDocument();
    expect(screen.getByText("Ada Contributor")).toBeInTheDocument();
    // formatTimestamp renders a non-placeholder for a real timestamp.
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("refetches with the trimmed search query", async () => {
    render(<AdminFrameworkDirectoryPanel />);
    await screen.findByText("Governance Operating Model");

    fireEvent.change(screen.getByPlaceholderText(/search by framework title/i), {
      target: { value: "gov" },
    });

    await waitFor(() =>
      expect(listAdminFrameworksV1AdminFrameworksGet).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: { query: "gov" } }),
      ),
    );
  });

  it("drops a framework from the list after a successful delist", async () => {
    vi.mocked(
      suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost,
    ).mockResolvedValue(
      ok({ framework_id: "framework-1", status: "suspended", reason: "spam" }),
    );

    render(<AdminFrameworkDirectoryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^delist$/i }));

    fireEvent.change(screen.getByPlaceholderText(/why is this framework/i), {
      target: { value: "Policy breach" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm delist/i }));

    await waitFor(() =>
      expect(
        screen.queryByText("Governance Operating Model"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText(/no published frameworks match this search/i),
    ).toBeInTheDocument();
  });

  it("keeps the row and surfaces an error when delist fails", async () => {
    vi.mocked(
      suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost,
    ).mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      request: new Request("http://testserver"),
      response: new Response(null, { status: 409 }),
    });

    render(<AdminFrameworkDirectoryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^delist$/i }));
    fireEvent.change(screen.getByPlaceholderText(/why is this framework/i), {
      target: { value: "Policy breach" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm delist/i }));

    expect(
      await screen.findByText("The request could not be completed."),
    ).toBeInTheDocument();
    expect(screen.getByText("Governance Operating Model")).toBeInTheDocument();
  });

  it("cancels the delist form without removing the row", async () => {
    render(<AdminFrameworkDirectoryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^delist$/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(
        screen.queryByPlaceholderText(/why is this framework/i),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Governance Operating Model")).toBeInTheDocument();
  });

  it("shows the empty state when no frameworks match", async () => {
    vi.mocked(listAdminFrameworksV1AdminFrameworksGet).mockResolvedValue(
      ok({ items: [] }),
    );

    render(<AdminFrameworkDirectoryPanel />);

    expect(
      await screen.findByText(/no published frameworks match this search/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error when the directory fails to load", async () => {
    vi.mocked(listAdminFrameworksV1AdminFrameworksGet).mockResolvedValue({
      data: undefined,
      error: { detail: "nope" },
      request: new Request("http://testserver"),
      response: new Response(null, { status: 500 }),
    });

    render(<AdminFrameworkDirectoryPanel />);

    expect(
      await screen.findByText("The request could not be completed."),
    ).toBeInTheDocument();
  });
});
