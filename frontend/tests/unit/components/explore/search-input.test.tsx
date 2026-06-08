import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchInput } from "@/components/modules/explore/search-input";

describe("SearchInput", () => {
  it("debounces marketplace search submissions", async () => {
    vi.useFakeTimers();
    const onSearch = vi.fn();

    render(<SearchInput initialValue="" onSearch={onSearch} />);

    fireEvent.change(screen.getByLabelText(/search frameworks/i), {
      target: { value: "risk" },
    });
    fireEvent.change(screen.getByLabelText(/search frameworks/i), {
      target: { value: "risk register" },
    });

    expect(onSearch).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(350);
    });

    expect(onSearch).toHaveBeenCalledTimes(1);
    expect(onSearch).toHaveBeenCalledWith("risk register");

    vi.useRealTimers();
  });
});
