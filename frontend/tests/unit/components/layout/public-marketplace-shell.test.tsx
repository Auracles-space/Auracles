import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";

describe("PublicMarketplaceShell", () => {
  it("keeps public marketplace pages connected to Auracles navigation", () => {
    render(
      <PublicMarketplaceShell>
        <h1>Explore frameworks</h1>
      </PublicMarketplaceShell>,
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
