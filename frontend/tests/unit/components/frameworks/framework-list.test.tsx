import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkList } from "@/components/modules/frameworks/framework-list";
import { listContributorFrameworks } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  listContributorFrameworks: vi.fn(),
}));

describe("FrameworkList", () => {
  beforeEach(() => {
    vi.mocked(listContributorFrameworks).mockReset();
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
