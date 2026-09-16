/**
 * Sections of the organization's Members tab.
 *
 * Setting up people is one admin job: see who is in the org, invite more, and
 * give them access through teams. The Members tab holds all three as sections;
 * the member list stays at the bare tab path so existing links keep working.
 * Invitations and teams are admin-only on the backend, so a plain member only
 * gets the list.
 */
import type { OrgActionCounts } from "@/lib/generated/types.gen";

/** Identifier of one Members section. */
export type MemberSectionId = "members" | "invitations" | "teams";

/** One Members section with its attention count. */
export type MemberSection = {
  id: MemberSectionId;
  label: string;
  count: number;
};

/** Section URL segments below the Members tab path. */
const SEGMENT_SECTIONS: Record<string, MemberSectionId> = {
  invitations: "invitations",
  teams: "teams",
};

/**
 * List the Members sections the caller can open, in display order.
 *
 * @param isAdmin - Whether the caller is an org owner or admin.
 * @param counts - The org's attention counts from `GET /v1/orgs/mine`.
 */
export function memberSections({
  isAdmin,
  counts,
}: {
  isAdmin: boolean;
  counts: OrgActionCounts | undefined;
}): MemberSection[] {
  const list: MemberSection = { id: "members", label: "Members", count: 0 };
  if (!isAdmin) return [list];
  return [
    list,
    { id: "invitations", label: "Invitations", count: counts?.invitations ?? 0 },
    { id: "teams", label: "Teams", count: 0 },
  ];
}

/**
 * Resolve which section a path under the Members tab shows.
 *
 * @param pathname - The current path.
 * @param base - The Members tab path, e.g. `/dashboard/organizations/{id}/members`.
 * @returns The section, or null when the path names no section.
 */
export function memberSectionFromPath(pathname: string, base: string): MemberSectionId | null {
  if (pathname === base || pathname === `${base}/`) return "members";
  const segment = pathname.startsWith(`${base}/`)
    ? pathname.slice(base.length + 1).split("/")[0]
    : "";
  return SEGMENT_SECTIONS[segment] ?? null;
}
