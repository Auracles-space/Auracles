/**
 * Typed event contract for terminal account-state 403 responses.
 *
 * When the backend rejects a request because the account is deactivated
 * (GDPR deletion / self-deactivation) or suspended, it returns a 403 with
 * `{error_code, message}`. The session-terminated interceptor publishes this
 * event so a single global listener can clear the session and bounce the user
 * to the login page — they can no longer use the app with that token.
 */

/** Window event name for a terminal session-state rejection. */
export const SESSION_TERMINATED_EVENT = "auracles:session-terminated";

/** Backend error codes that mean the session can never recover. */
const TERMINAL_ERROR_CODES = new Set(["account_deactivated", "account_suspended"]);

export type SessionTerminatedEventDetail = {
  /** The terminal error code from the backend body. */
  errorCode: string;
  /** Human-readable reason, surfaced on the login page. */
  message: string;
};

/**
 * Narrow an unknown 403 body to the terminal session-state contract.
 *
 * @param body - Parsed JSON body of a 403 response.
 * @returns The typed detail when the body is a terminal rejection, else null.
 */
export function buildSessionTerminatedDetail(
  body: unknown,
): SessionTerminatedEventDetail | null {
  if (typeof body !== "object" || body === null) {
    return null;
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null) {
    return null;
  }
  const errorCode = (detail as { error_code?: unknown }).error_code;
  const message = (detail as { message?: unknown }).message;
  if (typeof errorCode !== "string" || !TERMINAL_ERROR_CODES.has(errorCode)) {
    return null;
  }
  return {
    errorCode,
    message: typeof message === "string" ? message : "Your session has ended.",
  };
}
