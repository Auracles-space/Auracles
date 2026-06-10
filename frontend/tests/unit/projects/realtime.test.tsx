import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { authTokenStore } from "@/lib/auth/token-store";
import { useProjectRealtime } from "@/lib/projects/realtime";

type Listener = (event: { data: string }) => void;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  sent: string[] = [];
  private listeners = new Map<string, Listener[]>();

  constructor(readonly url: string) {
    MockWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  send(message: string): void {
    this.sent.push(message);
  }

  close(): void {
    return;
  }

  emit(type: string, payload: unknown = {}): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(payload) });
    }
  }
}

describe("useProjectRealtime", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
    authTokenStore.setState({
      accessToken: null,
      expiresAt: null,
      roles: [],
      totpVerified: false,
      userId: null,
    });
  });

  it("subscribes to the project channel after the backend auth_ok handshake", async () => {
    authTokenStore.setState({
      accessToken: "access-token",
      expiresAt: 4102444800,
      roles: ["operator"],
      totpVerified: true,
      userId: "operator-1",
    });
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() => useProjectRealtime("project-123"));
    const socket = MockWebSocket.instances[0];

    expect(socket.url).toBe("ws://localhost:8000/v1/ws");
    act(() => {
      socket.emit("open");
    });
    expect(socket.sent).toEqual([
      JSON.stringify({ token: "access-token", type: "auth" }),
    ]);

    act(() => {
      socket.emit("message", { type: "auth_ok", user_id: "operator-1" });
    });

    await waitFor(() => {
      expect(result.current.connected).toBe(true);
    });
    expect(socket.sent).toContain(
      JSON.stringify({ channel: "project:project-123", type: "subscribe" }),
    );
  });
});
