import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ListingPrice } from "@/components/ui/listing-price";

describe("ListingPrice", () => {
  it("renders a zero price as Free", () => {
    render(<ListingPrice price="0.00" currency="NGN" />);
    expect(screen.getByText("Free")).toBeInTheDocument();
  });

  it("marks a free listing with the accent colour, not a money figure", () => {
    // A buyer scanning a feed should see at a glance which listings cost
    // nothing, so free is emphasised rather than printed as a zero amount.
    render(<ListingPrice price="0.00" currency="NGN" />);
    expect(screen.getByText("Free").className).toContain("text-accent");
    expect(screen.queryByText(/0/)).not.toBeInTheDocument();
  });

  it("renders a priced listing as a formatted amount", () => {
    render(<ListingPrice price="25000.00" currency="NGN" />);
    expect(screen.getByText(/25,000/)).toBeInTheDocument();
    expect(screen.queryByText("Free")).not.toBeInTheDocument();
  });
});
