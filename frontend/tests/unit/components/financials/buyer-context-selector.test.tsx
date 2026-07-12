import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuyerContextSelector } from "@/components/modules/financials/buyer-context-selector";
import type { BuyerOption } from "@/lib/marketplace/purchase-context";

const options: BuyerOption[] = [
  { kind: "self", label: "Myself" },
  { kind: "org", orgId: "org-1", label: "Acme" },
];

describe("BuyerContextSelector", () => {
  it("renders one radio per option with a 44px touch target and marks the value selected", () => {
    render(<BuyerContextSelector options={options} value={options[0]} onChange={() => {}} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(screen.getByRole("radio", { name: /myself/i })).toBeChecked();
  });

  it("emits the chosen option on change", () => {
    const onChange = vi.fn();
    render(<BuyerContextSelector options={options} value={options[0]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: /acme/i }));
    expect(onChange).toHaveBeenCalledWith(options[1]);
  });
});
