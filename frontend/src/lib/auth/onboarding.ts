/**
 * Phase 1 onboarding decisions.
 *
 * Full profile management fields are deferred in the Phase 1 slice plan, so
 * this helper treats the existing verified account identity plus started KYC
 * as the Phase 1 completion threshold. Marketplace action enforcement remains
 * backend-owned in Phase 2.
 */
import type { CurrentUserResponse } from "@/lib/generated/types.gen";

export const ONBOARDING_PATH = "/settings/onboarding";

/**
 * Return whether the current user has completed Phase 1 onboarding.
 *
 * @param user - Current authenticated user profile from `/v1/auth/me`.
 */
export function isPhaseOneOnboardingComplete(user: CurrentUserResponse): boolean {
  const profileComplete = user.email_verified && user.display_name.trim().length > 0;
  const kycStarted = user.kyc_status === "pending" || user.kyc_status === "verified";
  return profileComplete && kycStarted;
}

/**
 * Narrow an untrusted `?next=` value to a same-origin path.
 *
 * The onboarding route takes its return destination from a query parameter, so
 * the value reaches us as attacker-controllable text. Anything that could leave
 * the origin — an absolute URL, a protocol-relative `//host`, or a backslash
 * variant browsers normalise to one — is discarded rather than sanitised.
 *
 * @param value - Raw `next` query parameter, if present.
 * @returns The path when it is safe to navigate to, otherwise null.
 */
export function toSafeInternalPath(value: string | undefined): string | null {
  if (!value || !value.startsWith("/")) {
    return null;
  }
  if (value.startsWith("//") || value.startsWith("/\\")) {
    return null;
  }
  return value;
}

/**
 * Route incomplete users to onboarding, otherwise preserve role landing.
 *
 * @param user - Current authenticated user profile from `/v1/auth/me`.
 * @param roleLandingPath - Destination selected from active roles.
 */
export function getOnboardingDestination(
  user: CurrentUserResponse,
  roleLandingPath: string,
): string {
  return isPhaseOneOnboardingComplete(user) ? roleLandingPath : ONBOARDING_PATH;
}
