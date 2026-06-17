/**
 * Browser-side response interceptor for access-token expiry (401).
 *
 * Access tokens are memory-only and live ~15 minutes; long-lived UI (the
 * notification poll, dashboards left open) will eventually fire a request with
 * an expired bearer and get a 401. This interceptor recovers transparently:
 * on a 401 it runs the single-flight refresh (rehydrating the access token
 * from the rotating refresh cookie) and retries the original request once with
 * the fresh bearer.
 *
 * The retry uses a direct `fetch`, NOT the shared hey-api client, so it never
 * re-enters this interceptor — exactly one retry, no recursion. Refresh/login
 * endpoints are skipped (their 401 is terminal, not a token-expiry signal).
 *
 * SSR-safe: install is a no-op outside the browser. The core is dependency-
 * injected so it can be unit-tested without the live client.
 */
import { client } from "@/lib/generated/sdk.gen";

import { refreshAccessToken } from "./refresh-client";
import { authTokenStore } from "./token-store";

/** Auth endpoints whose 401 must not trigger a refresh-and-retry loop. */
const NO_RETRY_PATHS = ["/v1/auth/refresh", "/v1/auth/login"];

/** Dependencies the 401 recovery core needs, injected for testability. */
type UnauthorizedRetryDeps = {
  refresh: () => Promise<boolean>;
  getToken: () => string | null;
  fetchImpl: typeof fetch;
};

/**
 * Recover a single 401 by refreshing the access token and retrying the request.
 *
 * @param response - The response returned for the original request.
 * @param request - The original request that produced the response.
 * @param deps - Refresh, token accessor, and fetch implementation.
 * @returns The retried response on successful recovery, else the original.
 */
export async function retryWithRefreshOn401(
  response: Response,
  request: Request,
  deps: UnauthorizedRetryDeps,
): Promise<Response> {
  if (response.status !== 401) {
    return response;
  }
  if (NO_RETRY_PATHS.some((path) => request.url.includes(path))) {
    return response;
  }

  const authHeader = request.headers.get("Authorization");
  const requestToken = authHeader?.startsWith("Bearer ")
    ? authHeader.substring(7)
    : null;
  const currentToken = deps.getToken();

  // Skip the refresh call if the token in memory has already changed from the one that
  // just failed, preventing concurrent 401s from triggering redundant refreshes.
  if (currentToken !== null && currentToken !== requestToken) {
    try {
      const retried = request.clone();
      retried.headers.set("Authorization", `Bearer ${currentToken}`);
      return await deps.fetchImpl(retried);
    } catch {
      return response;
    }
  }

  const refreshed = await deps.refresh();
  if (!refreshed) {
    return response;
  }

  const token = deps.getToken();
  if (!token) {
    return response;
  }

  try {
    const retried = request.clone();
    retried.headers.set("Authorization", `Bearer ${token}`);
    return await deps.fetchImpl(retried);
  } catch {
    // Replay failed (e.g. an already-consumed request body) — surface the
    // original 401 rather than throwing inside the transport layer.
    return response;
  }
}

let installed = false;

/**
 * Install the 401 refresh-and-retry interceptor exactly once per process.
 *
 * Safe to call from `configureBrowserClient` on every render; subsequent calls
 * are no-ops. Skipped during SSR (`window` undefined).
 */
export function installUnauthorizedRefreshInterceptor(): void {
  if (installed || typeof window === "undefined") {
    return;
  }
  installed = true;
  client.interceptors.response.use((response, request) =>
    retryWithRefreshOn401(response, request, {
      refresh: refreshAccessToken,
      getToken: () => authTokenStore.getState().accessToken,
      fetchImpl: (input: RequestInfo | URL, init?: RequestInit) =>
        fetch(input, init),
    }),
  );
}
