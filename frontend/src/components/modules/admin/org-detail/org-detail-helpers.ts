/**
 * Pure helpers for the admin organization detail page.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import type { AdminOrgOverviewResponse, AdminOrgResponse } from "@/lib/generated/types.gen";

/** Lifecycle key for an organization; closure outranks suspension. */
export function lifecycleKey(org: Pick<AdminOrgOverviewResponse, "deactivated_at" | "suspended_at">) {
  if (org.deactivated_at) return "deactivated";
  if (org.suspended_at) return "suspended";
  return "active";
}

/**
 * Turn a snake_case or dotted audit action into a sentence-case phrase.
 *
 * @param action - Raw action such as `org_kyb_document_viewed`.
 */
export function humaniseAction(action: string): string {
  const words = action.replace(/[._]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : action;
}

/**
 * Adapt the detail overview to the directory row shape the capabilities
 * dialog reads, so the existing dialog is reused unchanged.
 *
 * @param org - Organization overview from the detail endpoint.
 */
export function toDirectoryOrg(org: AdminOrgOverviewResponse): AdminOrgResponse {
  const capabilities: Record<string, string> = {};
  const reasons: Record<string, string> = {};
  for (const item of org.capabilities) {
    capabilities[item.capability] = item.status;
    if (item.status_reason) reasons[item.capability] = item.status_reason;
  }
  return {
    id: org.id,
    slug: org.slug,
    name: org.name,
    country: org.country,
    member_count: org.member_count,
    created_at: org.created_at,
    kyb_status: org.kyb_status,
    capabilities,
    capability_reasons: reasons,
  };
}

/**
 * Apply one capability transition to the overview without a refetch.
 *
 * @param org - Current overview.
 * @param capability - Capability that changed.
 * @param status - Its new status.
 * @param reason - Stored reason, or null when cleared.
 */
export function applyCapabilityChange(
  org: AdminOrgOverviewResponse,
  capability: string,
  status: string,
  reason: string | null,
): AdminOrgOverviewResponse {
  const next = { capability, status, status_reason: reason };
  const exists = org.capabilities.some((item) => item.capability === capability);
  return {
    ...org,
    capabilities: exists
      ? org.capabilities.map((item) => (item.capability === capability ? next : item))
      : [...org.capabilities, next],
  };
}
