import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DelistButton } from "@/components/modules/frameworks/delist-button";
import { PublishButton } from "@/components/modules/frameworks/publish-button";
import {
  publishFramework,
  unpublishFramework,
} from "@/lib/generated/sdk.gen";

const { refresh } = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  publishFramework: vi.fn(),
  unpublishFramework: vi.fn(),
}));

describe("PublishButton", () => {
  beforeEach(() => {
    vi.mocked(publishFramework).mockReset();
    refresh.mockReset();
  });

  it("publishes and refreshes the route on success", async () => {
    vi.mocked(publishFramework).mockResolvedValue({
      data: { id: "fw-1", status: "published" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<PublishButton frameworkId="fw-1" />);
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("shows the gate error when publish is blocked", async () => {
    vi.mocked(publishFramework).mockResolvedValue({
      data: undefined,
      error: { detail: "Framework must pass pipeline checks before publish." },
      response: new Response(null, { status: 409 }),
    });

    render(<PublishButton frameworkId="fw-1" />);
    fireEvent.click(screen.getByRole("button", { name: /^publish$/i }));

    expect(
      await screen.findByText(/must pass pipeline checks/i),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("DelistButton", () => {
  beforeEach(() => {
    vi.mocked(unpublishFramework).mockReset();
    refresh.mockReset();
  });

  it("requires confirmation before delisting, then refreshes", async () => {
    vi.mocked(unpublishFramework).mockResolvedValue({
      data: { id: "fw-1", status: "unpublished" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<DelistButton frameworkId="fw-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /delist from marketplace/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /confirm delist/i }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("surfaces a delist error", async () => {
    vi.mocked(unpublishFramework).mockResolvedValue({
      data: undefined,
      error: { detail: "Only published frameworks can be delisted." },
      response: new Response(null, { status: 409 }),
    });

    render(<DelistButton frameworkId="fw-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /delist from marketplace/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /confirm delist/i }));

    expect(
      await screen.findByText(/only published frameworks can be delisted/i),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
