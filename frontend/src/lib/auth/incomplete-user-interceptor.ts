/**
 * Browser-side response interceptor for incomplete-user 403s.
 *
 * Installs once on the shared hey-api client. When the backend returns
 * `{error_code, onboarding_url}` on a 403, the interceptor publishes a
 * window CustomEvent so the global listener can redirect the browser to
 * `/settings/onboarding?next=<attempted-path>&error_code=<code>`.
 *
 * Designed to be SSR-safe: no-op outside the browser, no router import.
 * Implementation peeks the response body via `.clone()` so the original
 * `Response` remains consumable by the form/error path that called the
 * generated SDK.
 *
 * Maps to: Phase 2 cross-cutting concern §6 (Incomplete-user rule).
 */
import { client } from "@/lib/generated/sdk.gen";

import {
  buildIncompleteUserDetail,
  INCOMPLETE_USER_EVENT,
  type IncompleteUserEventDetail,
} from "./incomplete-user-events";

let installed = false;

/**
 * Install the response interceptor exactly once per process.
 *
 * Safe to call from `configureBrowserClient` on every render; subsequent
 * calls are no-ops. Skipped during SSR (`window` undefined).
 */
export function installIncompleteUserInterceptor(): void {
  if (installed || typeof window === "undefined") {
    return;
  }
  installed = true;
  client.interceptors.response.use(async (response) => {
    if (response.status !== 403) {
      return response;
    }

    let parsed: unknown = null;
    try {
      parsed = await response.clone().json();
    } catch {
      return response;
    }

    const attemptedPath = `${window.location.pathname}${window.location.search}`;
    const detail = buildIncompleteUserDetail(parsed, attemptedPath);
    if (!detail) {
      return response;
    }

    window.dispatchEvent(
      new CustomEvent<IncompleteUserEventDetail>(INCOMPLETE_USER_EVENT, {
        detail,
      }),
    );

    return response;
  });
}
