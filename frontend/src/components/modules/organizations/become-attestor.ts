/**
 * Become-attestor entry resolution.
 *
 * Pure client-side logic that decides whether the user should create a new
 * organization, jump directly to a single eligible org's attestor tab, or
 * choose between multiple eligible organizations.
 */
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

/** An organization the current user can apply with plus its display status. */
export type AttestorEligibleOrg = {
  id: string;
  name: string;
  /** Existing attestor capability state, or null when no application exists. */
  attestorStatus: string | null;
};

/** The next step for the become-attestor front door. */
export type AttestorEntryResolution =
  | { kind: "create" }
  | { kind: "direct"; orgId: string }
  | { kind: "picker"; orgs: AttestorEligibleOrg[] };

const ATTESTOR_ENTRY_ROLES = new Set(["owner", "admin"]);

/**
 * Return the organizations that can open or resume attestor onboarding.
 *
 * @param orgs - Organizations returned by the existing "my orgs" endpoint.
 */
export function eligibleAttestorOrgs(
  orgs: MyOrganizationResponse[],
): AttestorEligibleOrg[] {
  return orgs
    .filter(
      (item) =>
        ATTESTOR_ENTRY_ROLES.has(item.role) &&
        item.capabilities?.attestor !== "active",
    )
    .map((item) => ({
      id: item.org.id,
      name: item.org.name,
      attestorStatus: item.capabilities?.attestor ?? null,
    }));
}

/**
 * Resolve how the front-door route should branch for the current user.
 *
 * @param orgs - Organizations returned by the existing "my orgs" endpoint.
 */
export function resolveAttestorEntry(
  orgs: MyOrganizationResponse[],
): AttestorEntryResolution {
  const eligible = eligibleAttestorOrgs(orgs);

  if (eligible.length === 0) {
    return { kind: "create" };
  }

  if (eligible.length === 1) {
    return { kind: "direct", orgId: eligible[0].id };
  }

  return { kind: "picker", orgs: eligible };
}
