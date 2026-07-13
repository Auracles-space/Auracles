import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "@/components/ui/toast";

/** Test harness exposing both toast tones through the public hook. */
function Harness() {
  const toast = useToast();
  return (
    <>
      <button onClick={() => toast.success("Framework published")} type="button">
        succeed
      </button>
      <button onClick={() => toast.error("Publish failed")} type="button">
        fail
      </button>
    </>
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe("ToastProvider", () => {
  it("announces a success toast in a live region when fired", () => {
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "succeed" }));

    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("Framework published");
  });

  it("styles an error toast with the error tone", () => {
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "fail" }));

    const message = screen.getByText("Publish failed");
    expect(message.closest("[data-tone]")).toHaveAttribute("data-tone", "error");
  });

  it("removes a toast when its dismiss control is clicked", () => {
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "succeed" }));
    fireEvent.click(
      screen.getByRole("button", { name: /dismiss notification/i }),
    );

    expect(screen.queryByText("Framework published")).not.toBeInTheDocument();
  });

  it("auto-dismisses a toast after the timeout", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Harness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "succeed" }));
    expect(screen.getByText("Framework published")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(screen.queryByText("Framework published")).not.toBeInTheDocument();
  });

  it("throws when useToast is called outside a provider", () => {
    // Silence the expected React error boundary console noise for this case.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Harness />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });
});
