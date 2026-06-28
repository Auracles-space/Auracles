import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/auth/server-session", () => ({
  getVerifiedSessionHintFromCookies: vi.fn().mockResolvedValue(null),
}));

describe("PublicMarketplaceShell", () => {
  it("keeps public marketplace pages connected to Auracles navigation", async () => {
    render(
      await PublicMarketplaceShell({ children: <h1>Explore frameworks</h1> }),
    );

    expect(
      screen.getByRole("link", { name: /^auracles$/i }),
    ).toHaveAttribute("href", "/");
    const headerNav = screen.getByRole("navigation", {
      name: /public marketplace navigation/i,
    });

    expect(within(headerNav).getByRole("link", { name: /^explore$/i })).toHaveAttribute(
      "href",
      "/explore",
    );
    expect(screen.getByRole("link", { name: /create framework/i })).toHaveAttribute(
      "href",
      "/dashboard/frameworks/new",
    );
    expect(screen.getByRole("heading", { name: /explore frameworks/i })).toBeInTheDocument();
  });
});
