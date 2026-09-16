/**
 * Sections of the organization's Attestor tab.
 *
 * Before approval the Attestor tab is only the application. Once the org is an
 * attestor, the application has nothing left to do (its approved coverage is
 * summarised above Offers), so the tab becomes the attestation work: incoming
 * offers and the review queue. Who sees which section mirrors what the backend
 * lets them load, so a reviewer never gets a section whose every request 403s.
 */
import type { OrgActionCounts } from "@/lib/generated/types.gen";

/** Identifier of one Attestor hub section; also its URL segment. */
export type AttestorSectionId = "offers" | "queue";

/** One Attestor hub section with its attention count. */
export type AttestorSection = {
  id: AttestorSectionId;
  label: string;
  count: number;
};

/** Capability statuses that mean the org has been an approved attestor. */
const APPROVED_CAPABILITIES = new Set(["active", "suspended", "revoked"]);

/**
 * List the hub sections the caller can open, in display order.
 *
 * Empty means the hub is off and the Attestor tab shows the application alone.
 * Offers need an active capability; the queue stays open to admins while
 * suspended or revoked so reviews still being settled remain reachable. A plain
 * member only ever reviews, and only while the org is active.
 *
 * @param isAdmin - Whether the caller is an org owner or admin.
 * @param capability - The org's attestor capability status, if any.
 * @param counts - The org's attention counts from `GET /v1/orgs/mine`.
 */
export function attestorHubSections({
  isAdmin,
  capability,
  counts,
}: {
  isAdmin: boolean;
  capability: string | undefined;
  counts: OrgActionCounts | undefined;
}): AttestorSection[] {
  if (!capability || !APPROVED_CAPABILITIES.has(capability)) return [];
  const queue: AttestorSection = { id: "queue", label: "Queue", count: counts?.queue ?? 0 };
  if (!isAdmin) return capability === "active" ? [queue] : [];

  if (capability !== "active") return [queue];
  return [{ id: "offers", label: "Offers", count: counts?.offers ?? 0 }, queue];
}

/**
 * The section to open when the Attestor tab is selected without a section.
 *
 * The first section that needs attention, else the queue, where the work is.
 *
 * @param sections - Sections from `attestorHubSections`; must not be empty.
 */
export function defaultAttestorSection(sections: AttestorSection[]): AttestorSectionId {
  return sections.find((section) => section.count > 0)?.id ?? "queue";
}
