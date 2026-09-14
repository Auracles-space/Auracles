/**
 * Human labels for organization capabilities.
 *
 * One source for every owner-facing organization surface (shell banners,
 * the organizations list, the capabilities card, the public profile) so a
 * capability is named the same way everywhere. Keyed by the API's raw
 * capability key; callers fall back to the raw key for anything unknown.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */

export const CAPABILITY_LABELS: Record<string, string> = {
  attestor: "Attestor",
  contributor: "Contributor",
  operator: "Operator",
};

/**
 * Resolve the display label for a capability key.
 *
 * @param capability - Raw capability key from the API.
 * @returns The human label, or the raw key when it is not a known capability.
 */
export function capabilityLabel(capability: string): string {
  return CAPABILITY_LABELS[capability] ?? capability;
}
