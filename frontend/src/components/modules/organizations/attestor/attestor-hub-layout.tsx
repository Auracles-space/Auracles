"use client";

/**
 * Attestor tab layout: the application before approval, a hub after it.
 *
 * Once the org is an attestor, offers and the review queue sit under one tab
 * as sections at `/attestor/{section}`; the application has nothing left to
 * do, so its old link lands on a section instead. The sections use the
 * shared segmented control rather than a second underline tablist, so they
 * read as a level below the organization tabs (the queue has its own
 * Active/History tabs beneath it). Links to a section the caller cannot open
 * are replaced with the one they should land on.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Spinner } from "@/components/ui/spinner";
import {
  attestorHubSections,
  defaultAttestorSection,
  type AttestorSectionId,
} from "@/lib/organizations/attestor-hub";

/** Sections that only exist once the org is an attestor. */
const HUB_ONLY_SEGMENTS = new Set(["offers", "queue"]);

/**
 * Render the Attestor tab around its current section.
 *
 * @param children - The routed section page.
 */
export function AttestorHubLayout({ children }: { children: ReactNode }) {
  const { orgId, role, capabilities, counts } = useOrganization();
  const pathname = usePathname();
  const router = useRouter();

  const base = `/dashboard/organizations/${orgId}/attestor`;
  const segment = pathname.startsWith(`${base}/`)
    ? pathname.slice(base.length + 1).split("/")[0]
    : undefined;
  const sections = attestorHubSections({
    isAdmin: role === "owner" || role === "admin",
    capability: capabilities?.["attestor"],
    counts,
  });

  let redirectTo: string | null = null;
  if (sections.length === 0) {
    if (segment && HUB_ONLY_SEGMENTS.has(segment)) redirectTo = base;
  } else if (!sections.some((section) => section.id === segment)) {
    redirectTo = `${base}/${defaultAttestorSection(sections)}`;
  }

  useEffect(() => {
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);

  if (redirectTo) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {sections.length > 1 ? (
        <SegmentedControl<AttestorSectionId>
          className="sm:inline-flex"
          label="Attestor sections"
          onChange={(id) => router.push(`${base}/${id}`)}
          options={sections.map((section) => ({
            value: section.id,
            label: section.label,
            count: section.count,
          }))}
          value={segment as AttestorSectionId}
        />
      ) : null}
      {children}
    </div>
  );
}
