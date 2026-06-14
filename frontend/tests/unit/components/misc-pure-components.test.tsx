import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchPanel } from "@/components/modules/explore/search-panel";
import { VersionRadios } from "@/components/modules/frameworks/version-radios";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(""),
}));

describe("VersionRadios", () => {
  it("renders the three change types and reports a selection", () => {
    const onChange = vi.fn();
    render(<VersionRadios onChange={onChange} value="fix" />);

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    fireEvent.click(radios[radios.length - 1]);
    expect(onChange).toHaveBeenCalled();
  });
});

describe("SearchPanel", () => {
  it("renders a search input wired to the explore query", () => {
    const { container } = render(<SearchPanel initialValue="risk" />);
    expect(container.querySelector("input")).toBeInTheDocument();
  });
});
