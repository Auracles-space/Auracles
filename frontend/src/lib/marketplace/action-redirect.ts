/**
 * Marketplace action redirect helpers.
 *
 * Read-only marketplace routes remain public, but action attempts that fail
 * because onboarding is incomplete should move the user to onboarding with the
 * original intent preserved.
 */
export const MARKETPLACE_ONBOARDING_ERROR_CODES = [
  "kyc_required",
  "profile_required",
  "role_required",
] as const;

type MarketplaceOnboardingErrorCode =
  (typeof MARKETPLACE_ONBOARDING_ERROR_CODES)[number];

type MarketplaceActionRedirectInput = {
  error: unknown;
  pathname: string;
};

/**
 * Return the onboarding redirect for action-gated 403 responses.
 *
 * @param input - Generated-client error payload and the browser path to resume.
 * @returns Onboarding URL with `next`, or `null` for non-onboarding errors.
 */
export function resolveMarketplaceActionRedirect({
  error,
  pathname,
}: MarketplaceActionRedirectInput): string | null {
  if (!isOnboardingErrorCode(readErrorCode(error))) {
    return null;
  }

  return `/settings/onboarding?next=${encodeURIComponent(pathname)}`;
}

/**
 * Read an API `error_code` without trusting the rest of the payload shape.
 *
 * @param error - Unknown generated-client error payload.
 * @returns Error code string when present.
 */
function readErrorCode(error: unknown): string | null {
  if (
    error &&
    typeof error === "object" &&
    "error_code" in error &&
    typeof error.error_code === "string"
  ) {
    return error.error_code;
  }
  return null;
}

/**
 * Check whether an API error code represents incomplete onboarding.
 *
 * @param code - Candidate API error code.
 * @returns True when marketplace actions should route to onboarding.
 */
function isOnboardingErrorCode(
  code: string | null,
): code is MarketplaceOnboardingErrorCode {
  return MARKETPLACE_ONBOARDING_ERROR_CODES.some((known) => known === code);
}
