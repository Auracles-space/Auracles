import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserSessionGate } from "@/components/modules/layout/browser-session-gate";
import {
  clearBrowserSessionHintCookie,
  ensureBrowserAccessToken,
} from "@/lib/auth/current-user-session";
import { authTokenStore, clearAuthToken } from "@/lib/auth/token-store";

vi.mock("@/lib/auth/current-user-session", () => ({
  ensureBrowserAccessToken: vi.fn(),
  clearBrowserSessionHintCookie: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: { getState: vi.fn() },
  clearAuthToken: vi.fn(),
}));

describe("BrowserSessionGate", () => {
  beforeEach(() => {
    vi.mocked(ensureBrowserAccessToken).mockReset();
    vi.mocked(clearBrowserSessionHintCookie).mockReset();
    vi.mocked(clearAuthToken).mockReset();
    vi.mocked(authTokenStore.getState).mockReturnValue({
      accessToken: null,
      roles: [],
    } as never);
    vi.stubGlobal("location", { assign: vi.fn() });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders children immediately when an access token is already in memory", () => {
    vi.mocked(authTokenStore.getState).mockReturnValue({
      accessToken: "in-memory-token",
      roles: ["contributor"],
    } as never);

    render(
      <BrowserSessionGate>
        <p>protected content</p>
      </BrowserSessionGate>,
    );

    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(ensureBrowserAccessToken).not.toHaveBeenCalled();
  });

  it("rehydrates the token then renders children when the refresh session is valid", async () => {
    vi.mocked(ensureBrowserAccessToken).mockResolvedValue(true);

    render(
      <BrowserSessionGate>
        <p>protected content</p>
      </BrowserSessionGate>,
    );

    // Gated while the refresh round-trip is in flight.
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    expect(ensureBrowserAccessToken).toHaveBeenCalledTimes(1);
  });

  it("clears the stale session and redirects to login when no session remains", async () => {
    vi.mocked(ensureBrowserAccessToken).mockResolvedValue(false);

    render(
      <BrowserSessionGate>
        <p>protected content</p>
      </BrowserSessionGate>,
    );

    await waitFor(() => {
      expect(location.assign).toHaveBeenCalledWith("/login");
    });
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    expect(clearAuthToken).toHaveBeenCalled();
    expect(clearBrowserSessionHintCookie).toHaveBeenCalled();
  });
});
