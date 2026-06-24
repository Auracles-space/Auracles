import { resolveApiBaseUrl } from "@/lib/api-base";
import {
  client,
  refreshToken as generatedRefreshToken,
} from "@/lib/generated/sdk.gen";

import { clearAuthToken, setAccessTokenFromJwt } from "./token-store";

const API_BASE_URL = resolveApiBaseUrl();

// Single-flight guard. The refresh cookie is rotated server-side on every use,
// and reusing a rotated token trips reuse-detection (the backend revokes the
// whole token family -> session bounce). React StrictMode double-invokes
// effects and multiple components can request a token at once, so concurrent
// callers must share one in-flight request instead of each hitting /auth/refresh.
let inFlightRefresh: Promise<boolean> | null = null;

/**
 * Rehydrate the in-memory access token from the refresh cookie.
 *
 * Concurrent calls share a single network request so the rotating refresh
 * token is never sent twice in parallel.
 *
 * @returns True when a new access token was stored, false otherwise.
 */
export async function refreshAccessToken(): Promise<boolean> {
  if (inFlightRefresh) {
    return inFlightRefresh;
  }

  inFlightRefresh = performRefresh().finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}

/**
 * Perform the actual refresh request and update the token store.
 */
async function performRefresh(): Promise<boolean> {
  client.setConfig({
    baseUrl: API_BASE_URL,
    credentials: "include",
    cache: "no-store",
  });

  const result = await generatedRefreshToken();
  if (!result.response.ok || !result.data?.access_token) {
    clearAuthToken();
    return false;
  }

  setAccessTokenFromJwt(result.data.access_token);
  return true;
}
