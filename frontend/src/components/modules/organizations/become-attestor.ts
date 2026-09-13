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
  /** Business-verification state; only a verified org can open an application. */
  kybStatus: string;
  /** False when the org must finish verification before it can apply. */
  eligible: boolean;
};

/** The next step for the become-attestor front door. */
export type AttestorEntryResolution =
  | { kind: "create" }
  | { kind: "direct"; orgId: string }
  | { kind: "picker"; orgs: AttestorEligibleOrg[] };

const ATTESTOR_ENTRY_ROLES = new Set(["owner", "admin"]);

/**
 * Return every organization the user could apply with, verified or not.
 *
 * Unverified orgs are kept and marked ineligible so the picker can say why
 * they cannot apply yet and route to verification, rather than dropping them
 * and walking the user into creating a duplicate organization.
 *
 * @param orgs - Organizations returned by the existing "my orgs" endpoint.
 */
export function attestorEntryOrgs(
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
      kybStatus: item.kyb_status ?? "unverified",
      // Business verification precedes every capability, so an unverified
      // org cannot open an application; the API would refuse it.
      eligible: item.kyb_status === "verified",
    }));
}

/**
 * Return the organizations that can open or resume attestor onboarding now.
 *
 * @param orgs - Organizations returned by the existing "my orgs" endpoint.
 */
export function eligibleAttestorOrgs(
  orgs: MyOrganizationResponse[],
): AttestorEligibleOrg[] {
  return attestorEntryOrgs(orgs).filter((item) => item.eligible);
}

/**
 * Resolve how the front-door route should branch for the current user.
 *
 * @param orgs - Organizations returned by the existing "my orgs" endpoint.
 */
export function resolveAttestorEntry(
  orgs: MyOrganizationResponse[],
): AttestorEntryResolution {
  const candidates = attestorEntryOrgs(orgs);
  const eligible = candidates.filter((item) => item.eligible);

  if (eligible.length === 0) {
    // An owner whose orgs are all still in verification should see them and
    // why they are blocked, not a prompt to create yet another organization.
    return candidates.length === 0 ? { kind: "create" } : { kind: "picker", orgs: candidates };
  }

  if (eligible.length === 1) {
    return { kind: "direct", orgId: eligible[0].id };
  }

  return { kind: "picker", orgs: candidates };
}
