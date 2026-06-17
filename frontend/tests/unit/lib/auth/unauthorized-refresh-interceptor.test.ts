import { describe, expect, it, vi } from "vitest";

import { retryWithRefreshOn401 } from "@/lib/auth/unauthorized-refresh-interceptor";

/**
 * Build the dependency bundle the interceptor core consumes, with sensible
 * defaults each test can override.
 */
function makeDeps(overrides: {
  refresh?: () => Promise<boolean>;
  getToken?: () => string | null;
  fetchImpl?: typeof fetch;
} = {}) {
  return {
    refresh: overrides.refresh ?? vi.fn(async () => true),
    getToken: overrides.getToken ?? vi.fn(() => "new-token"),
    fetchImpl:
      overrides.fetchImpl ??
      (vi.fn(async () => new Response(null, { status: 200 })) as unknown as typeof fetch),
  };
}

describe("retryWithRefreshOn401", () => {
  it("passes a non-401 response through without refreshing", async () => {
    const deps = makeDeps();
    const response = new Response(null, { status: 200 });
    const request = new Request("http://api/v1/notifications");

    const result = await retryWithRefreshOn401(response, request, deps);

    expect(result).toBe(response);
    expect(deps.refresh).not.toHaveBeenCalled();
    expect(deps.fetchImpl).not.toHaveBeenCalled();
  });

  it("refreshes and retries once with the new bearer on a 401", async () => {
    const retried = new Response(null, { status: 200 });
    const fetchImpl = vi.fn(async () => retried) as unknown as typeof fetch;
    let token = "stale";
    const refresh = vi.fn(async () => {
      token = "new-token";
      return true;
    });
    const deps = makeDeps({
      fetchImpl,
      refresh,
      getToken: () => token,
    });
    const response = new Response(null, { status: 401 });
    const request = new Request("http://api/v1/notifications", {
      headers: { Authorization: "Bearer stale" },
    });

    const result = await retryWithRefreshOn401(response, request, deps);

    expect(deps.refresh).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const sent = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Request;
    expect(sent.headers.get("Authorization")).toBe("Bearer new-token");
    expect(result).toBe(retried);
  });

  it("returns the original 401 when refresh fails", async () => {
    const deps = makeDeps({
      refresh: vi.fn(async () => false),
      getToken: vi.fn(() => null),
    });
    const response = new Response(null, { status: 401 });
    const request = new Request("http://api/v1/notifications");

    const result = await retryWithRefreshOn401(response, request, deps);

    expect(result).toBe(response);
    expect(deps.fetchImpl).not.toHaveBeenCalled();
  });

  it("does not retry the refresh endpoint itself", async () => {
    const deps = makeDeps();
    const response = new Response(null, { status: 401 });
    const request = new Request("http://api/v1/auth/refresh", {
      method: "POST",
    });

    const result = await retryWithRefreshOn401(response, request, deps);

    expect(result).toBe(response);
    expect(deps.refresh).not.toHaveBeenCalled();
    expect(deps.fetchImpl).not.toHaveBeenCalled();
  });

  it("retries immediately without refreshing if the token in memory has already advanced past what the failed request used", async () => {
    const retried = new Response(null, { status: 200 });
    const fetchImpl = vi.fn(async () => retried) as unknown as typeof fetch;
    const deps = makeDeps({
      fetchImpl,
      getToken: vi.fn(() => "new-token"),
    });
    const response = new Response(null, { status: 401 });
    const request = new Request("http://api/v1/notifications", {
      headers: { Authorization: "Bearer stale-token" },
    });

    const result = await retryWithRefreshOn401(response, request, deps);

    expect(deps.refresh).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const sent = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Request;
    expect(sent.headers.get("Authorization")).toBe("Bearer new-token");
    expect(result).toBe(retried);
  });

  it("retries immediately without refreshing if the failed request had no token but in-memory token is present", async () => {
    const retried = new Response(null, { status: 200 });
    const fetchImpl = vi.fn(async () => retried) as unknown as typeof fetch;
    const deps = makeDeps({
      fetchImpl,
      getToken: vi.fn(() => "new-token"),
    });
    const response = new Response(null, { status: 401 });
    const request = new Request("http://api/v1/notifications");

    const result = await retryWithRefreshOn401(response, request, deps);

    expect(deps.refresh).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const sent = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Request;
    expect(sent.headers.get("Authorization")).toBe("Bearer new-token");
    expect(result).toBe(retried);
  });

  it("refreshes if the in-memory token is null, even if it is different from request token", async () => {
    const retried = new Response(null, { status: 200 });
    const fetchImpl = vi.fn(async () => retried) as unknown as typeof fetch;
    const deps = makeDeps({
      fetchImpl,
      getToken: vi.fn(() => null),
      refresh: vi.fn(async () => false),
    });
    const response = new Response(null, { status: 401 });
    const request = new Request("http://api/v1/notifications", {
      headers: { Authorization: "Bearer stale-token" },
    });

    await retryWithRefreshOn401(response, request, deps);

    expect(deps.refresh).toHaveBeenCalledTimes(1);
  });
});
