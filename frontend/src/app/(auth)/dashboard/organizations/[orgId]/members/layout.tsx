/**
 * Members tab layout: the member list, invitations, and teams as sections.
 */
import type { ReactNode } from "react";

import { MembersSectionsLayout } from "@/components/modules/organizations/members-sections-layout";

export default function OrgMembersLayout({ children }: { children: ReactNode }) {
  return <MembersSectionsLayout>{children}</MembersSectionsLayout>;
}
