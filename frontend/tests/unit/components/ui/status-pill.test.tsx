import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { describeStatus, StatusPill } from "@/components/ui/status-pill";

describe("describeStatus", () => {
  it("maps operational statuses to one label and tone everywhere", () => {
    expect(describeStatus("needs_info")).toEqual({ label: "Needs info", tone: "warning" });
    expect(describeStatus("in_review")).toEqual({ label: "In review", tone: "warning" });
    expect(describeStatus("needs_admin")).toEqual({ label: "Needs admin", tone: "error" });
    expect(describeStatus("matching")).toEqual({ label: "Finding attestor", tone: "info" });
    expect(describeStatus("approved")).toEqual({ label: "Approved", tone: "success" });
    expect(describeStatus("revoked")).toEqual({ label: "Revoked", tone: "error" });
  });

  it("title-cases unknown statuses with a neutral tone", () => {
    expect(describeStatus("some_new_state")).toEqual({
      label: "Some New State",
      tone: "neutral",
    });
  });
});

describe("StatusPill", () => {
  it("renders the mapped label and tone classes", () => {
    render(<StatusPill status="needs_admin" />);

    const pill = screen.getByText("Needs admin");
    expect(pill.className).toContain("text-error");
    expect(pill.className).toContain("rounded-badge");
  });

  it("accepts a label override without changing the tone", () => {
    render(<StatusPill label="Trial passed" status="passed" />);

    expect(screen.getByText("Trial passed").className).toContain("text-success");
  });
});
