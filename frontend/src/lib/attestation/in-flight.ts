/**
 * Attestation requests that are still in progress.
 *
 * The server refuses a second request for the same framework and review type
 * while one is in flight (`_reject_duplicate_in_flight_request`). The UI uses
 * the same status set to name the running review beside "Request attestation"
 * and to disable that review type in the request form.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */

/** Mirrors `IN_FLIGHT_ATTESTATION_STATUSES` in the backend attestation service. */
export const IN_FLIGHT_ATTESTATION_STATUSES: ReadonlySet<string> = new Set([
  "pending_fee",
  "pending_owner_consent",
  "matching",
  "offered",
  "accepted",
  "report_submitted",
  "disputed",
  "needs_admin",
  "resolved",
]);

/** Display names for framework review types. */
export const REVIEW_TYPE_LABELS: Record<string, string> = {
  quality: "Quality",
  compliance: "Compliance",
  expert: "Expert",
  provenance: "Provenance",
};

/** The fields of an attestation request this module reads. */
export type InFlightCandidate = {
  id: string;
  target_id: string;
  review_type?: string | null;
  status: string;
};

/**
 * The requests for one framework that are still in progress.
 *
 * @param attestations - The viewer's attestation requests.
 * @param targetId - The framework to match.
 * @returns The in-progress requests for that framework, in input order.
 */
export function inFlightAttestationsFor<T extends InFlightCandidate>(
  attestations: readonly T[],
  targetId: string,
): T[] {
  return attestations.filter(
    (attestation) =>
      attestation.target_id === targetId &&
      IN_FLIGHT_ATTESTATION_STATUSES.has(attestation.status),
  );
}

/** Public wording for a published attestation outcome. */
export const ATTESTED_OUTCOME_LABELS: Record<string, string> = {
  approved: "Attested",
  conditional: "Conditionally attested",
};

/** The fields of a public attestation badge this module reads. */
export type BadgeCandidate = {
  review_type: string;
  outcome: string;
  newer_version_exists: boolean;
};

/**
 * The review types attested for the framework's current version.
 *
 * The server refuses a review type already settled for the current version
 * (`review_type_already_attested`); a newer version reopens it. Badges arrive
 * newest first, so the first badge per review type wins.
 *
 * @param badges - Public badges from the framework detail endpoint.
 * @returns Outcome keyed by review type, current-version badges only.
 */
export function attestedOnCurrentVersion(
  badges: readonly BadgeCandidate[],
): Record<string, string> {
  const attested: Record<string, string> = {};
  for (const badge of badges) {
    if (badge.newer_version_exists || badge.review_type in attested) continue;
    attested[badge.review_type] = badge.outcome;
  }
  return attested;
}
