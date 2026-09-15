/**
 * Unit coverage for ExpandableText: long free text is clamped behind a
 * Read more toggle, and typed line breaks survive display.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExpandableText } from "@/components/ui/expandable-text";

describe("ExpandableText", () => {
  it("shows short text in full with no toggle", () => {
    render(<ExpandableText text="A short brief." />);

    expect(screen.getByText("A short brief.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /read more/i })).toBeNull();
  });

  it("clamps long text behind Read more and expands it", () => {
    const long = "Due diligence ".repeat(40).trim();
    render(<ExpandableText text={long} />);

    const toggle = screen.getByRole("button", { name: /read more/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    expect(screen.getByRole("button", { name: /show less/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("keeps typed line breaks and wraps unbroken strings", () => {
    render(<ExpandableText text={"Line one\nLine two"} />);

    const body = screen.getByText(/Line one/);
    expect(body.textContent).toBe("Line one\nLine two");
    expect(body.className).toMatch(/whitespace-pre-wrap/);
    expect(body.className).toMatch(/break-words/);
  });
});
