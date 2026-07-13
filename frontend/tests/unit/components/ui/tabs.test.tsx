import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Tabs, type TabItem } from "@/components/ui/tabs";

/** Render the Tabs primitive with a given set of items. */
function renderTabs(tabs: TabItem[]) {
  return render(
    <Tabs activeId="open" label="Projects" onChange={vi.fn()} tabs={tabs} />,
  );
}

describe("Tabs count badge", () => {
  it("shows a compact badge with the exact value on hover when count > 0", () => {
    renderTabs([{ id: "open", label: "Open", count: 1234 }]);

    const badge = screen.getByText("1.2K");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", "1,234");
  });

  it("renders no badge when the count is 0", () => {
    renderTabs([{ id: "open", label: "Open", count: 0 }]);

    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders no badge when the count is omitted", () => {
    const { container } = renderTabs([{ id: "open", label: "Open" }]);

    // The only element inside the tab button is its text label — no badge span.
    expect(container.querySelector("[title]")).toBeNull();
  });
});
