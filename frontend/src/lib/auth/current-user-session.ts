/**
 * Browser helpers for hydrating the authenticated user from the existing
 * refresh-cookie session.
 *
 * Access tokens are memory-only, so a hard reload may leave protected UI with
 * a valid `session_hint` but no bearer token in the client store. These
 * helpers rehydrate the token through the refresh endpoint before loading the
 * current-user profile.
 */
import { configureBrowserClient, getAccessTokenHeaders } from "./form-client";
import { refreshAccessToken } from "./refresh-client";
import { authTokenStore, clearAuthToken } from "./token-store";
import { getCurrentUser } from "@/lib/generated/sdk.gen";
import type { CurrentUserResponse } from "@/lib/generated/types.gen";

/**
 * Clear the readable session-hint cookie from the current browser.
 */
export function clearBrowserSessionHintCookie(): void {
  document.cookie =
    "session_hint=; Max-Age=0; Path=/; SameSite=Lax";
}

/**
 * Ensure the in-memory access token exists, rehydrating through refresh when
 * a valid browser session still exists.
 */
export async function ensureBrowserAccessToken(): Promise<boolean> {
  if (authTokenStore.getState().accessToken) {
    return true;
  }

  return refreshAccessToken();
}

/**
 * Load the current authenticated user, refreshing the access token when
 * necessary.
 */
export async function loadCurrentUserSession(): Promise<CurrentUserResponse | null> {
  configureBrowserClient();
  const hasToken = await ensureBrowserAccessToken();
  if (!hasToken) {
    clearAuthToken();
    clearBrowserSessionHintCookie();
    return null;
  }

  const result = await getCurrentUser({
    headers: getAccessTokenHeaders(),
  });
  if (!result.response.ok || !result.data) {
    clearAuthToken();
    return null;
  }

  return result.data;
}
