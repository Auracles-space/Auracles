/**
 * Landing demand teaser — concrete, current demand shown to someone deciding
 * whether to contribute, and silence whenever there is nothing real to say.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemandTeaser } from "@/components/modules/landing/demand-teaser";

describe("DemandTeaser", () => {
  it("names what people are searching for and finding nothing", () => {
    // Concrete terms persuade where a link labelled "market demand" does not.
    render(
      <DemandTeaser
        terms={[
          { term: "soc 2", searcher_count: 14 },
          { term: "iso 27001", searcher_count: 9 },
          { term: "incident response", searcher_count: 6 },
        ]}
      />,
    );

    expect(screen.getByText(/soc 2/)).toBeInTheDocument();
    expect(screen.getByText(/iso 27001/)).toBeInTheDocument();
    expect(screen.getByText(/incident response/)).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/demand");
  });

  it("renders nothing when there is no demand to show", () => {
    // An empty teaser on the landing page reads as a broken section, and
    // "nobody wants anything" is the opposite of the message.
    const { container } = render(<DemandTeaser terms={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when demand could not be loaded", () => {
    const { container } = render(<DemandTeaser terms={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows fewer than three terms without padding the sentence", () => {
    render(<DemandTeaser terms={[{ term: "soc 2", searcher_count: 4 }]} />);

    expect(screen.getByText(/soc 2/)).toBeInTheDocument();
  });
});
