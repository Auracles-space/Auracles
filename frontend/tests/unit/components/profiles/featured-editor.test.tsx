import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FeaturedEditor } from "@/components/modules/profiles/featured-editor";
import type { ProfileFeatured } from "@/lib/generated/types.gen";

const frameworks = [
  { id: "fw-1", title: "Diligence Playbook" },
  { id: "fw-2", title: "Onboarding Kit" },
];

describe("FeaturedEditor", () => {
  it("adds a blank free-form spotlight", () => {
    const onChange = vi.fn();
    render(<FeaturedEditor value={[]} onChange={onChange} frameworks={frameworks} />);

    fireEvent.click(screen.getByRole("button", { name: /add featured/i }));

    expect(onChange).toHaveBeenCalledWith([{ title: "" }]);
  });

  it("pins a framework and clears the free-form title", () => {
    const onChange = vi.fn();
    const value: ProfileFeatured[] = [{ title: "Draft" }];
    render(
      <FeaturedEditor value={value} onChange={onChange} frameworks={frameworks} />,
    );

    fireEvent.change(screen.getByLabelText("Pin a framework"), {
      target: { value: "fw-1" },
    });

    expect(onChange).toHaveBeenCalledWith([
      { title: null, framework_id: "fw-1" },
    ]);
  });

  it("hides a framework already pinned in another card", () => {
    const value: ProfileFeatured[] = [
      { framework_id: "fw-1" },
      { title: "" },
    ];
    render(
      <FeaturedEditor value={value} onChange={vi.fn()} frameworks={frameworks} />,
    );

    // Both cards expose a picker; the second must not offer fw-1 again.
    const pickers = screen.getAllByLabelText("Pin a framework");
    const secondCardOptions = Array.from(
      pickers[1].querySelectorAll("option"),
    ).map((option) => option.textContent);

    expect(secondCardOptions).not.toContain("Diligence Playbook");
    expect(secondCardOptions).toContain("Onboarding Kit");
  });

  it("hides free-form fields once a framework is pinned", () => {
    const value: ProfileFeatured[] = [{ framework_id: "fw-1" }];
    render(
      <FeaturedEditor value={value} onChange={vi.fn()} frameworks={frameworks} />,
    );

    expect(screen.queryByLabelText("Featured title")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Showing this framework's live card/i),
    ).toBeInTheDocument();
  });

  it("removes an entry", () => {
    const onChange = vi.fn();
    const value: ProfileFeatured[] = [{ title: "Solo" }];
    render(
      <FeaturedEditor value={value} onChange={onChange} frameworks={frameworks} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /remove/i }));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});
