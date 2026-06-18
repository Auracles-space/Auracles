import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HeaderSearch } from "@/components/modules/layout/header-search";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

describe("HeaderSearch", () => {
  it("navigates to the deduped explore feed with the typed query on submit", () => {
    push.mockReset();
    render(<HeaderSearch />);

    const input = screen.getByRole("searchbox", { name: /search/i });
    fireEvent.change(input, { target: { value: "  risk register  " } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(push).toHaveBeenCalledWith("/explore?q=risk+register");
  });

  it("clears the query and routes to the full feed when submitted empty", () => {
    push.mockReset();
    render(<HeaderSearch />);

    fireEvent.submit(
      (screen.getByRole("searchbox") as HTMLInputElement).closest(
        "form",
      ) as HTMLFormElement,
    );

    expect(push).toHaveBeenCalledWith("/explore");
  });
});
