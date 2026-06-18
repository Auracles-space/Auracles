import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SortMenu } from "@/components/modules/explore/sort-menu";

describe("SortMenu", () => {
  it("shows the active sort label and links each option preserving filters", () => {
    render(
      <SortMenu
        active={{ sector: "healthcare", sort: "newest" }}
        current="newest"
      />,
    );

    // Trigger reflects the current sort.
    expect(screen.getByText("Sort: Newest")).toBeInTheDocument();
    // Options are hidden until the menu is opened.
    expect(
      screen.queryByRole("menuitem", { name: "Top rated" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /sort: newest/i }));

    // Each option is a link that keeps the active filter and resets the page.
    const topRated = screen.getByRole("menuitem", { name: "Top rated" });
    const href = topRated.getAttribute("href") ?? "";
    expect(href).toContain("sort=top-rated");
    expect(href).toContain("sector=healthcare");
    expect(href).toContain("page=1");
  });

  it("closes the menu on an outside click", () => {
    render(
      <div>
        <SortMenu active={{ sort: "newest" }} current="newest" />
        <button type="button">outside</button>
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: /sort: newest/i }));
    expect(screen.getByRole("menuitem", { name: "Top rated" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("button", { name: "outside" }));
    expect(
      screen.queryByRole("menuitem", { name: "Top rated" }),
    ).not.toBeInTheDocument();
  });
});
