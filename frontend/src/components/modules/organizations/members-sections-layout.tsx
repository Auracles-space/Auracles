"use client";

/**
 * Members tab layout: the member list, invitations, and teams as sections.
 *
 * The list stays at the bare `/members` path; invitations and teams live at
 * `/members/{section}`. Sections use the shared segmented control, as the
 * Attestor tab does. A plain member only has the list, so gets no control, and
 * a link into an admin-only section lands on the list instead.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Spinner } from "@/components/ui/spinner";
import {
  memberSectionFromPath,
  memberSections,
  type MemberSectionId,
} from "@/lib/organizations/member-sections";

/**
 * Render the Members tab around its current section.
 *
 * @param children - The routed section page.
 */
export function MembersSectionsLayout({ children }: { children: ReactNode }) {
  const { orgId, role, counts } = useOrganization();
  const pathname = usePathname();
  const router = useRouter();

  const base = `/dashboard/organizations/${orgId}/members`;
  const sections = memberSections({ isAdmin: role === "owner" || role === "admin", counts });
  const current = memberSectionFromPath(pathname, base);
  const allowed = sections.some((section) => section.id === current);
  const redirectTo = allowed ? null : base;

  useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);

  if (redirectTo || !current) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {sections.length > 1 ? (
        <SegmentedControl<MemberSectionId>
          className="max-w-4xl sm:inline-flex"
          label="Member sections"
          onChange={(id) => router.push(id === "members" ? base : `${base}/${id}`)}
          options={sections.map((section) => ({
            value: section.id,
            label: section.label,
            count: section.count,
          }))}
          value={current}
        />
      ) : null}
      {children}
    </div>
  );
}
