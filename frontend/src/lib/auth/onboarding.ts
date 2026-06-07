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
