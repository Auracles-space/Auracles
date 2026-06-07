/**
 * Generated-client configuration helpers for browser auth forms.
 *
 * Centralises API base URL and credential mode so components call generated
 * SDK functions without duplicating transport setup.
 */
import { client } from "@/lib/generated/sdk.gen";

import { authTokenStore } from "./token-store";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Configure the generated client for browser calls that need cookies.
 */
export function configureBrowserClient(): void {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
    credentials: "include",
  });
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
