/**
 * Regression coverage for cross-domain API base resolution.
 *
 * Production runs the frontend and backend on different registrable domains, so
 * auth cookies are kept first-party by proxying browser traffic through a
 * relative `/api` path. A relative path only resolves in the browser; server
 * fetches must fall back to the absolute backend origin. These tests lock that
 * branch so the `session_hint` cookie keeps reaching the routing middleware.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveApiBaseUrl, resolveWebsocketUrl } from "@/lib/api-base";

const ORIGINAL_ENV = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.unstubAllGlobals();
});

describe("resolveApiBaseUrl", () => {
  it("returns the relative proxy path in the browser", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api";
    // jsdom provides `window`, i.e. the browser runtime.
    expect(resolveApiBaseUrl()).toBe("/api");
  });

  it("falls back to the absolute backend origin on the server", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api";
    process.env.BACKEND_ORIGIN = "https://backend.example.com";
    vi.stubGlobal("window", undefined);
    expect(resolveApiBaseUrl()).toBe("https://backend.example.com");
  });

  it("passes an absolute configured URL through unchanged", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com";
    expect(resolveApiBaseUrl()).toBe("https://api.example.com");
  });
});

describe("resolveWebsocketUrl", () => {
  it("prefers an explicit WS URL", () => {
    process.env.NEXT_PUBLIC_WS_URL = "wss://rt.example.com/v1/ws";
    expect(resolveWebsocketUrl()).toBe("wss://rt.example.com/v1/ws");
  });

  it("derives wss from the backend origin when the API base is relative", () => {
    delete process.env.NEXT_PUBLIC_WS_URL;
    process.env.NEXT_PUBLIC_API_URL = "/api";
    process.env.BACKEND_ORIGIN = "https://backend.example.com";
    expect(resolveWebsocketUrl()).toBe("wss://backend.example.com/v1/ws");
  });

  it("derives ws from an absolute http API base in local dev", () => {
    delete process.env.NEXT_PUBLIC_WS_URL;
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
    expect(resolveWebsocketUrl()).toBe("ws://localhost:8000/v1/ws");
  });
});
