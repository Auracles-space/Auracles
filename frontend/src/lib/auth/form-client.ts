/**
 * Generated-client configuration helpers for browser auth forms.
 *
 * Centralises API base URL and credential mode so components call generated
 * SDK functions without duplicating transport setup.
 */
import { resolveApiBaseUrl } from "@/lib/api-base";
import { client } from "@/lib/generated/sdk.gen";

import { installIncompleteUserInterceptor } from "./incomplete-user-interceptor";
import { authTokenStore } from "./token-store";
import { installUnauthorizedRefreshInterceptor } from "./unauthorized-refresh-interceptor";

const API_BASE_URL = resolveApiBaseUrl();

/**
 * Configure the generated client for browser calls that need cookies.
 *
 * Also installs the shared response interceptors: incomplete-user (403 →
 * onboarding redirect) and unauthorized-refresh (401 → transparent token
 * refresh and single retry), so neither concern needs per-form wiring.
 */
export function configureBrowserClient(): void {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
    credentials: "include",
  });
  installIncompleteUserInterceptor();
  installUnauthorizedRefreshInterceptor();
}

/**
 * Build Authorization headers from the in-memory access token when present.
 *
 * @returns Headers object suitable for generated-client options.
 */
export function getAccessTokenHeaders(): Record<string, string> {
  const token = authTokenStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Convert generated-client errors into safe user-facing copy.
 *
 * @param error - Unknown error shape from the generated client.
 */
export function describeGeneratedError(error: unknown): string {
  if (
    error &&
    typeof error === "object" &&
    "detail" in error &&
    typeof error.detail === "string"
  ) {
    return error.detail;
  }
  return "The request could not be completed.";
}

/**
 * Get the current raw access token from the auth store.
 *
 * @returns The raw JWT string, or null if unauthenticated.
 */
export function getAccessToken(): string | null {
  return authTokenStore.getState().accessToken;
}
