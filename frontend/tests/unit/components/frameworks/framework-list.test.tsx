import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkList } from "@/components/modules/frameworks/framework-list";
import { ensureBrowserAccessToken } from "@/lib/auth/current-user-session";
import { listContributorFrameworks } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  ensureBrowserAccessToken: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  listContributorFrameworks: vi.fn(),
}));

describe("FrameworkList", () => {
  beforeEach(() => {
    vi.mocked(listContributorFrameworks).mockReset();
    vi.mocked(ensureBrowserAccessToken).mockReset();
    // Default: a hard reload still has a valid refresh session, so the
    // in-memory access token rehydrates before any data fetch.
    vi.mocked(ensureBrowserAccessToken).mockResolvedValue(true);
  });

  it("rehydrates the in-memory access token before fetching frameworks", async () => {
    vi.mocked(listContributorFrameworks).mockResolvedValue({
      data: [],
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<FrameworkList />);

    await screen.findByText(/no frameworks yet/i);
    expect(ensureBrowserAccessToken).toHaveBeenCalled();
  });

  it("does not call the API when no session can be rehydrated", async () => {
    vi.mocked(ensureBrowserAccessToken).mockResolvedValue(false);

    render(<FrameworkList />);

    expect(await screen.findByText(/session has expired/i)).toBeInTheDocument();
    expect(listContributorFrameworks).not.toHaveBeenCalled();
  });

  it("renders the empty state when the contributor has no frameworks", async () => {
    vi.mocked(listContributorFrameworks).mockResolvedValue({
      data: [],
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<FrameworkList />);

    expect(await screen.findByText(/no frameworks yet/i)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    vi.mocked(listContributorFrameworks).mockResolvedValue({
      data: undefined,
      error: { detail: "Frameworks are unavailable." },
      response: new Response(null, { status: 502 }),
    });

    render(<FrameworkList />);

    expect(
      await screen.findByText(/frameworks are unavailable/i),
    ).toBeInTheDocument();
  });

  it("lists owned frameworks with status and open link", async () => {
    vi.mocked(listContributorFrameworks).mockResolvedValue({
      data: [
        {
          id: "fw-1",
          title: "Board Risk Operating System",
          status: "published",
          category: "framework",
          version: "1.0.0",
          price: "499.00",
          currency: "USD",
        },
      ],
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<FrameworkList />);

    expect(
      await screen.findByText(/board risk operating system/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open/i })).toHaveAttribute(
      "href",
      "/dashboard/frameworks/fw-1",
    );
  });
});
