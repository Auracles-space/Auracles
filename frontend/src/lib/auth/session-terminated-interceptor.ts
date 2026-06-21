/**
 * Browser-side response interceptor for terminal account-state 403s.
 *
 * When the backend returns a 403 whose body carries a terminal error code
 * (`account_deactivated` or `account_suspended`), this interceptor publishes a
 * window CustomEvent so the global listener can clear the session and redirect
 * to login. Unlike the incomplete-user 403 (recoverable via onboarding) and the
 * 401 token-expiry path (recoverable via refresh), this state is terminal.
 *
 * SSR-safe: install is a no-op outside the browser. The response body is read
 * via `.clone()` so the original Response stays consumable by callers.
 */
import { client } from "@/lib/generated/sdk.gen";

import {
  buildSessionTerminatedDetail,
  SESSION_TERMINATED_EVENT,
  type SessionTerminatedEventDetail,
} from "./session-terminated-events";

let installed = false;

/**
 * Install the terminal-session interceptor exactly once per process.
 *
 * Safe to call on every render; subsequent calls are no-ops. Skipped during SSR.
 */
export function installSessionTerminatedInterceptor(): void {
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

    const detail = buildSessionTerminatedDetail(parsed);
    if (!detail) {
      return response;
    }

    window.dispatchEvent(
      new CustomEvent<SessionTerminatedEventDetail>(SESSION_TERMINATED_EVENT, {
        detail,
      }),
    );

    return response;
  });
}
