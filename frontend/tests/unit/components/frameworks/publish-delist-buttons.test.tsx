import {
  fireEvent,
  render,
  screen,
  waitFor,
  type RenderResult,
} from "@testing-library/react";
import { type ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DelistButton } from "@/components/modules/frameworks/delist-button";
import { RelistButton } from "@/components/modules/frameworks/relist-button";
import { PublishButton } from "@/components/modules/frameworks/publish-button";
import { ToastProvider } from "@/components/ui/toast";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";

const api = {
  publish: vi.fn(),
  relist: vi.fn(),
  unpublish: vi.fn(),
} as unknown as FrameworkApi;

/** Render a component beneath the toast provider it now depends on. */
function renderWithToast(ui: ReactElement): RenderResult {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

const { refresh } = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

describe("PublishButton", () => {
  beforeEach(() => {
    vi.mocked(api.publish).mockReset();
    refresh.mockReset();
  });

  it("publishes and refreshes the route on success", async () => {
    vi.mocked(api.publish).mockResolvedValue({ id: "fw-1" } as never);

    renderWithToast(<PublishButton api={api} frameworkId="fw-1" />);
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(
      await screen.findByText(/framework published/i),
    ).toBeInTheDocument();
  });

  it("shows the gate error when publish is blocked", async () => {
    vi.mocked(api.publish).mockRejectedValue(
      new Error("Framework must pass pipeline checks before publish."),
    );

    renderWithToast(<PublishButton api={api} frameworkId="fw-1" />);
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));

    expect(
      await screen.findByText(/must pass pipeline checks/i),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("DelistButton", () => {
  beforeEach(() => {
    vi.mocked(api.unpublish).mockReset();
    refresh.mockReset();
  });

  it("opens a confirm modal before delisting, then refreshes", async () => {
    vi.mocked(api.unpublish).mockResolvedValue({ id: "fw-1" } as never);

    renderWithToast(<DelistButton api={api} frameworkId="fw-1" />);
    // No request fires until the modal confirm is clicked.
    fireEvent.click(
      screen.getByRole("button", { name: /delist from marketplace/i }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(api.unpublish).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /delist framework/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(await screen.findByText(/framework delisted/i)).toBeInTheDocument();
  });

  it("surfaces a delist error", async () => {
    vi.mocked(api.unpublish).mockRejectedValue(
      new Error("Only published frameworks can be delisted."),
    );

    renderWithToast(<DelistButton api={api} frameworkId="fw-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /delist from marketplace/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /delist framework/i }));

    expect(
      await screen.findByText(/only published frameworks can be delisted/i),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("RelistButton", () => {
  beforeEach(() => {
    vi.mocked(api.relist).mockReset();
    refresh.mockReset();
  });

  it("opens a confirm modal before relisting, then refreshes", async () => {
    vi.mocked(api.relist).mockResolvedValue({ id: "fw-1" } as never);

    renderWithToast(<RelistButton api={api} frameworkId="fw-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /relist on marketplace/i }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(api.relist).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /relist framework/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(await screen.findByText(/framework relisted/i)).toBeInTheDocument();
  });

  it("surfaces a relist error", async () => {
    vi.mocked(api.relist).mockRejectedValue(
      new Error("Only unpublished Frameworks can be relisted."),
    );

    renderWithToast(<RelistButton api={api} frameworkId="fw-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /relist on marketplace/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /relist framework/i }));

    expect(
      await screen.findByText(/only unpublished frameworks can be relisted/i),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
