/**
 * Public demand map — unmet demand is legible, the floor is stated, and the
 * empty state explains itself rather than looking broken.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemandMap } from "@/components/modules/explore/demand-map";
import type { DemandMapResponse } from "@/lib/generated/types.gen";

function demand(overrides: Partial<DemandMapResponse> = {}): DemandMapResponse {
  return {
    terms: [
      { term: "soc", searcher_count: 14 },
      { term: "readiness", searcher_count: 6 },
    ],
    filters: [
      {
        filters: { sector: "financial services", jurisdiction: "NG" },
        searcher_count: 9,
      },
    ],
    period_from: "2026-04-01",
    min_searchers: 3,
    ...overrides,
  };
}

describe("DemandMap", () => {
  it("ranks what people searched for and did not find", () => {
    render(<DemandMap demand={demand()} />);

    expect(screen.getByText("soc")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText("readiness")).toBeInTheDocument();
  });

  it("shows filter demand in plain words, not raw filter keys", () => {
    // "sector: financial services" is the operator's language; the API key is ours.
    render(<DemandMap demand={demand()} />);

    expect(screen.getByText(/Financial Services/i)).toBeInTheDocument();
    expect(screen.queryByText(/sector=/)).not.toBeInTheDocument();
  });

  it("states the floor so the list does not read as exhaustive", () => {
    // Anything quieter than the floor is deliberately absent. Saying so stops
    // a contributor concluding there is no demand for what they had in mind.
    render(<DemandMap demand={demand()} />);

    expect(screen.getByText(/at least 3 people/i)).toBeInTheDocument();
  });

  it("explains an empty map instead of rendering a blank page", () => {
    render(<DemandMap demand={demand({ terms: [], filters: [] })} />);

    expect(screen.getByText(/Nothing to report yet/i)).toBeInTheDocument();
  });

  it("tells the reader the API is unavailable rather than showing zero demand", () => {
    // A failed fetch must never look like "nobody wants anything" — that is a
    // false signal a contributor could act on.
    render(<DemandMap demand={null} />);

    expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument();
  });

  it("omits its own heading when embedded in a surface that has one", () => {
    // The workspace tab titles the panel itself; two h1s in one page is wrong
    // for a screen reader.
    render(<DemandMap demand={demand()} showHeader={false} />);

    expect(
      screen.queryByRole("heading", { name: /what the market is asking for/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("soc")).toBeInTheDocument();
  });
});
