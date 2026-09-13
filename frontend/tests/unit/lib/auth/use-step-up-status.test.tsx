import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetStepUpGate, setStepUpVerifiedUntil } from "@/lib/auth/step-up-gate";
import { authTokenStore } from "@/lib/auth/token-store";
import { useStepUpStatus } from "@/lib/auth/use-step-up-status";

const sdkMock = vi.hoisted(() => ({
  readStepUp: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  readStepUpV1AuthStepUpGet: sdkMock.readStepUp,
  client: { interceptors: { response: { use: vi.fn() } }, setConfig: vi.fn() },
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

describe("useStepUpStatus", () => {
  beforeEach(() => {
    resetStepUpGate();
    sdkMock.readStepUp.mockReset();
    authTokenStore.setState({ accessToken: "token" });
  });

  afterEach(() => {
    vi.useRealTimers();
    resetStepUpGate();
  });

  it("loads the window from the API on mount and reports minutes left", async () => {
    sdkMock.readStepUp.mockResolvedValue({
      data: {
        active: true,
        verified_until: new Date(Date.now() + 8 * 60_000 + 30_000).toISOString(),
      },
      response: { ok: true, status: 200 },
    });

    const { result } = renderHook(() => useStepUpStatus());

    await waitFor(() => expect(result.current.active).toBe(true));
    expect(result.current.minutesLeft).toBe(9);
  });

  it("reports inactive when the API says no window is open", async () => {
    sdkMock.readStepUp.mockResolvedValue({
      data: { active: false, verified_until: null },
      response: { ok: true, status: 200 },
    });

    const { result } = renderHook(() => useStepUpStatus());

    await waitFor(() => expect(sdkMock.readStepUp).toHaveBeenCalled());
    expect(result.current.active).toBe(false);
    expect(result.current.minutesLeft).toBe(0);
  });

  it("follows the shared store when a prompt opens a window later", async () => {
    sdkMock.readStepUp.mockResolvedValue({
      data: { active: false, verified_until: null },
      response: { ok: true, status: 200 },
    });
    const { result } = renderHook(() => useStepUpStatus());
    await waitFor(() => expect(sdkMock.readStepUp).toHaveBeenCalled());

    act(() => {
      setStepUpVerifiedUntil(Date.now() + 120_000);
    });

    expect(result.current.active).toBe(true);
    expect(result.current.minutesLeft).toBe(2);
  });

  it("expires on its own when the window closes", async () => {
    vi.useFakeTimers();
    sdkMock.readStepUp.mockResolvedValue({
      data: { active: false, verified_until: null },
      response: { ok: true, status: 200 },
    });
    const { result } = renderHook(() => useStepUpStatus());
    act(() => {
      setStepUpVerifiedUntil(Date.now() + 20_000);
    });
    expect(result.current.active).toBe(true);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(45_000);
    });

    expect(result.current.active).toBe(false);
  });
});
