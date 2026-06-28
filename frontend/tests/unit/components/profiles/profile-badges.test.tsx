import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KycSeal, RoleBadge } from "@/components/modules/profiles/profile-badges";

describe("RoleBadge", () => {
  it("renders a friendly label for a known role", () => {
    render(<RoleBadge role="contributor" />);

    expect(screen.getByText("Contributor")).toBeInTheDocument();
  });

  it("falls back to the raw value for an unknown role", () => {
    render(<RoleBadge role="curator" />);

    expect(screen.getByText("curator")).toBeInTheDocument();
  });
});

describe("KycSeal", () => {
  it("renders the verified seal when verified", () => {
    render(<KycSeal verified />);

    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("renders nothing when not verified", () => {
    const { container } = render(<KycSeal verified={false} />);

    expect(container).toBeEmptyDOMElement();
  });
});
