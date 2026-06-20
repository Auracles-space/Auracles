import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Tabs } from "@/components/ui/tabs";

const TABS = [
  { id: "open", label: "Open" },
  { id: "posted", label: "Posted" },
  { id: "engagements", label: "Engagements" },
];

describe("Tabs", () => {
  it("renders each tab and marks only the active one selected", () => {
    render(<Tabs tabs={TABS} activeId="posted" onChange={vi.fn()} label="Projects" />);

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(screen.getByRole("tab", { name: "Posted" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Open" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("reports the clicked tab", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} activeId="open" onChange={onChange} label="Projects" />);

    fireEvent.click(screen.getByRole("tab", { name: "Engagements" }));
    expect(onChange).toHaveBeenCalledWith("engagements");
  });

  it("moves selection with arrow keys and wraps at the ends", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} activeId="open" onChange={onChange} label="Projects" />);

    fireEvent.keyDown(screen.getByRole("tab", { name: "Open" }), {
      key: "ArrowRight",
    });
    expect(onChange).toHaveBeenCalledWith("posted");

    fireEvent.keyDown(screen.getByRole("tab", { name: "Open" }), {
      key: "ArrowLeft",
    });
    expect(onChange).toHaveBeenCalledWith("engagements");
  });

  it("uses roving tabindex so only the active tab is in the tab order", () => {
    render(<Tabs tabs={TABS} activeId="posted" onChange={vi.fn()} label="Projects" />);

    expect(screen.getByRole("tab", { name: "Posted" })).toHaveAttribute(
      "tabindex",
      "0",
    );
    expect(screen.getByRole("tab", { name: "Open" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
  });
});
