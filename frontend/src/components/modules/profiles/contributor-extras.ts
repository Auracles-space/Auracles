/**
 * Contributor profile extras loader.
 *
 * The canonical profile composes a Contributor's published Frameworks,
 * reputation, and attestation badge from the existing Explore contributor
 * endpoint, so that data has a single backend source. Returns empty extras for
 * non-contributors or when the contributor has nothing public yet (the Explore
 * endpoint 404s when there are no published Frameworks).
 *
 * Caller configures the generated client first (server or browser).
 */
import { getExploreContributorProfile } from "@/lib/generated/sdk.gen";
import type {
  ExploreAttestationBadge,
  ExploreFrameworkCard,
  ReputationSummary,
} from "@/lib/generated/types.gen";

export type ContributorExtras = {
  frameworks: ExploreFrameworkCard[];
  reputation: ReputationSummary | null;
  attestationBadge: ExploreAttestationBadge | null;
};

const EMPTY: ContributorExtras = {
  frameworks: [],
  reputation: null,
  attestationBadge: null,
};

/**
 * Load a Contributor's published Frameworks, reputation, and attestation badge.
 *
 * @param userId - The profile owner's id.
 * @param roles - The profile owner's roles.
 * @returns Contributor extras, or empty values when not applicable.
 */
export async function loadContributorExtras(
  userId: string,
  roles: string[],
): Promise<ContributorExtras> {
  if (!roles.includes("contributor")) {
    return EMPTY;
  }
  const result = await getExploreContributorProfile({
    path: { contributor_id: userId },
  });
  if (!result.response.ok || !result.data) {
    return EMPTY;
  }
  return {
    frameworks: result.data.published_frameworks ?? [],
    reputation: result.data.reputation ?? null,
    attestationBadge: result.data.attestation_badge ?? null,
  };
}
