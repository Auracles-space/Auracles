/**
 * Generated-client configuration helpers for browser auth forms.
 *
 * Centralises API base URL and credential mode so components call generated
 * SDK functions without duplicating transport setup.
 */
import { resolveApiBaseUrl } from "@/lib/api-base";
import { client } from "@/lib/generated/sdk.gen";

import { installIncompleteUserInterceptor } from "./incomplete-user-interceptor";
import { installStepUpInterceptor } from "./step-up-interceptor";
import { authTokenStore } from "./token-store";
import { installUnauthorizedRefreshInterceptor } from "./unauthorized-refresh-interceptor";

const API_BASE_URL = resolveApiBaseUrl();

/**
 * Configure the generated client for browser calls that need cookies.
 *
 * Also installs the shared response interceptors: incomplete-user (403 →
 * onboarding redirect), step-up (403 `step_up_required` → one 2FA prompt and
 * a single replay), and unauthorized-refresh (401 → transparent token refresh
 * and single retry), so none of them needs per-form wiring.
 */
export function configureBrowserClient(): void {
  client.setConfig({
    baseUrl: API_BASE_URL,
    cache: "no-store",
    credentials: "include",
  });
  installIncompleteUserInterceptor();
  installStepUpInterceptor();
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
 * Reads, in order: a string `detail`, a list of 422 entries or plain strings,
 * then a dict `detail` (`message` first, else a humanised `error_code`).
 *
 * @param error - Unknown error shape from the generated client.
 */
export function describeGeneratedError(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const { detail } = error as { detail: unknown };
    // Handler-raised HTTPException: detail is a plain string.
    if (typeof detail === "string") {
      return detail;
    }
    // detail may be an array of Pydantic 422 { msg, loc, ... } entries, or a
    // list of plain-string failures raised by a handler (e.g. the report
    // quality gate). Surface every message so the user learns why the request
    // was rejected instead of a generic fallback.
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) => {
          if (typeof entry === "string") {
            return entry;
          }
          if (entry && typeof entry === "object" && "msg" in entry) {
            return String((entry as { msg: unknown }).msg);
          }
          return "";
        })
        .filter(Boolean);
      if (messages.length > 0) {
        return messages.join(" ");
      }
    }
    // Org routes raise a structured `{ error_code, message }` dict. The
    // message is written for people; the code is a stable identifier, so it
    // is only shown (humanised) when no message accompanies it.
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const { error_code: errorCode, message } = detail as {
        error_code?: unknown;
        message?: unknown;
      };
      if (typeof message === "string" && message.trim()) {
        return message;
      }
      if (typeof errorCode === "string" && errorCode.trim()) {
        return humaniseErrorCode(errorCode);
      }
    }
  }
  return "The request could not be completed.";
}

/** Turn a snake_case error code (`step_up_required`) into sentence case. */
function humaniseErrorCode(code: string): string {
  const words = code.trim().split(/[_\s]+/).filter(Boolean).join(" ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Get the current raw access token from the auth store.
 *
 * @returns The raw JWT string, or null if unauthenticated.
 */
export function getAccessToken(): string | null {
  return authTokenStore.getState().accessToken;
}
