import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

describe("AuthenticatedAppShell", () => {
  it("renders persistent product navigation around app pages", () => {
    render(
      <AuthenticatedAppShell>
        <h1>Frameworks</h1>
      </AuthenticatedAppShell>,
    );

    expect(screen.getAllByRole("link", { name: /^auracles$/i })[0]).toHaveAttribute(
      "href",
      "/explore",
    );

    const appNav = screen.getByRole("navigation", {
      name: /^application navigation$/i,
    });

    expect(within(appNav).getByRole("link", { name: /frameworks/i })).toHaveAttribute(
      "href",
      "/dashboard/frameworks",
    );
    expect(within(appNav).getByRole("link", { name: /library/i })).toHaveAttribute(
      "href",
      "/library",
    );
    expect(within(appNav).getByRole("link", { name: /settings/i })).toHaveAttribute(
      "href",
      "/settings/account",
    );
  });
});
