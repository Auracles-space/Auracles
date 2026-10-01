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

  it("does not re-emit when only the callback identity changes", () => {
    // The real loop: `SearchPanel` builds `onSearch` with
    // `useCallback(..., [router, searchParams])`, so navigating changes its
    // identity, which re-ran this effect, which navigated again — every 300ms
    // for as long as the tab stayed open. Each navigation re-rendered the
    // server component and refetched the catalog, which is what put ~6 req/s
    // of identical queries on staging.
    vi.useFakeTimers();
    const first = vi.fn();
    const { rerender } = render(
      <SearchInput initialValue="" onSearch={first} />,
    );

    fireEvent.change(screen.getByLabelText(/search frameworks/i), {
      target: { value: "risk" },
    });
    act(() => {
      vi.advanceTimersByTime(350);
    });
    expect(first).toHaveBeenCalledTimes(1);

    // A fresh identity, same query — exactly what the parent re-render does.
    const second = vi.fn();
    rerender(<SearchInput initialValue="" onSearch={second} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(second).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("does not search on mount for the query it was given", () => {
    // Arriving at /explore?q=risk already has its results; re-emitting the
    // same query navigates for nothing.
    vi.useFakeTimers();
    const onSearch = vi.fn();

    render(<SearchInput initialValue="risk" onSearch={onSearch} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(onSearch).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("still emits when the user clears the box", () => {
    // Clearing is a real change and must reach the parent, or the filter
    // sticks in the URL with no way to remove it.
    vi.useFakeTimers();
    const onSearch = vi.fn();

    render(<SearchInput initialValue="risk" onSearch={onSearch} />);
    fireEvent.change(screen.getByLabelText(/search frameworks/i), {
      target: { value: "" },
    });
    act(() => {
      vi.advanceTimersByTime(350);
    });

    expect(onSearch).toHaveBeenCalledWith("");
    vi.useRealTimers();
  });
});
