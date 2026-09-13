/**
 * Typed event contract for backend incomplete-user 403 responses.
 *
 * Backend dependencies (`require_role`, `require_kyc_verified`,
 * `require_profile_complete`, GDPR consent gates, `require_step_up` when 2FA
 * is not enrolled) return 403 +
 * `{error_code, onboarding_url}` on action endpoints. The browser-side
 * response interceptor publishes this event so a single listener can route
 * the user to onboarding without coupling every form to error-handling logic.
 *
 * Maps to: Phase 2 cross-cutting concern §6 (Incomplete-user rule).
 */

export const INCOMPLETE_USER_EVENT = "auracles:incomplete-user" as const;

export type IncompleteUserErrorCode =
  | "kyc_required"
  | "email_unverified"
  | "profile_required"
  | "role_required"
  | "consent_required"
  | "totp_setup_required";

export type IncompleteUserEventDetail = {
  errorCode: IncompleteUserErrorCode;
  onboardingUrl: string;
  attemptedPath: string;
};

const INCOMPLETE_USER_ERROR_CODES = new Set<string>([
  "kyc_required",
  "email_unverified",
  "profile_required",
  "role_required",
  "consent_required",
  "totp_setup_required",
]);

/**
 * Check whether an unknown backend value is a supported incomplete-user code.
 *
 * @param code - Candidate `error_code` value from the response body.
 */
export function isIncompleteUserErrorCode(
  code: unknown,
): code is IncompleteUserErrorCode {
  return typeof code === "string" && INCOMPLETE_USER_ERROR_CODES.has(code);
}

/**
 * Type guard that narrows an unknown JSON body to the backend 403 contract.
 *
 * @param body - Parsed JSON body of a 403 response.
 */
export function isIncompleteUserPayload(
  body: unknown,
): body is { detail: Record<string, unknown> } | Record<string, unknown> {
  if (!body || typeof body !== "object") {
    return false;
  }
  const root = body as Record<string, unknown>;
  const candidate =
    root.detail && typeof root.detail === "object"
      ? (root.detail as Record<string, unknown>)
      : root;
  return (
    isIncompleteUserErrorCode(candidate.error_code) &&
    typeof candidate.onboarding_url === "string"
  );
}

/**
 * Extract the typed event detail from a backend 403 body.
 *
 * @param body - Parsed JSON body of a 403 response.
 * @param attemptedPath - The browser path that triggered the request.
 */
export function buildIncompleteUserDetail(
  body: unknown,
  attemptedPath: string,
): IncompleteUserEventDetail | null {
  if (!isIncompleteUserPayload(body)) {
    return null;
  }
  const root = body as Record<string, unknown>;
  const candidate = (
    root.detail && typeof root.detail === "object"
      ? root.detail
      : root
  ) as Record<string, unknown>;
  if (
    !isIncompleteUserErrorCode(candidate.error_code) ||
    typeof candidate.onboarding_url !== "string"
  ) {
    return null;
  }
  const errorCode = candidate.error_code;
  const onboardingUrl = candidate.onboarding_url;
  return { errorCode, onboardingUrl, attemptedPath };
}
