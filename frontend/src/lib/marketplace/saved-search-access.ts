/**
 * Saved-search access rules.
 *
 * The saved-search API is operator-only (`require_role("operator")` on every
 * endpoint). Two surfaces decide whether to offer it — the authenticated nav
 * and the Explore catalog — and they disagreed: Explore offered the save form
 * to any signed-in user, so a contributor could name a search, submit it, and
 * be bounced into the onboarding redirect by the 403. One definition here, so
 * a role change moves both surfaces at once.
 */

/** Roles the saved-search endpoints accept. */
export const SAVED_SEARCH_ROLES = ["operator"] as const;

/**
 * Whether a role set may create and list saved searches.
 *
 * @param roles - Active roles from the verified session hint.
 */
export function canUseSavedSearches(roles: readonly string[]): boolean {
  return SAVED_SEARCH_ROLES.some((role) => roles.includes(role));
}
