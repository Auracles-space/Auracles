"use client";

/**
 * Attestor tab layout: the application before approval, a hub after it.
 *
 * Once the org is an attestor, offers, the review queue, and the application
 * record sit under one tab as sections at `/attestor/{section}`. The section
 * nav is a segmented control rather than a second underline tablist, so it
 * reads as a level below the organization tabs (the queue has its own
 * Active/History tabs beneath it). Links to a section the caller cannot open
 * are replaced with the one they should land on.
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { Spinner } from "@/components/ui/spinner";
import {
  attestorHubSections,
  defaultAttestorSection,
  type AttestorSection,
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
        <SectionNav activeId={segment} base={base} sections={sections} />
      ) : null}
      {children}
    </div>
  );
}

/**
 * Segmented links between hub sections, with attention counts.
 *
 * @param props - Sections, the open section, and the Attestor tab's base path.
 */
function SectionNav({
  sections,
  activeId,
  base,
}: {
  sections: AttestorSection[];
  activeId: string | undefined;
  base: string;
}) {
  return (
    <nav aria-label="Attestor sections">
      <ul className="grid auto-cols-fr grid-flow-col gap-1 rounded-xl border border-border-default bg-surface-1 p-1 sm:inline-grid">
        {sections.map((section) => {
          const active = section.id === activeId;
          return (
            <li key={section.id}>
              <Link
                aria-current={active ? "page" : undefined}
                className={`flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                  active
                    ? "bg-surface-3 text-foreground"
                    : "text-foreground-muted hover:bg-surface-2 hover:text-foreground"
                }`}
                href={`${base}/${section.id}`}
              >
                {section.label}
                {section.count > 0 ? (
                  <span
                    className={`inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 py-0.5 text-xs font-semibold tabular-nums ${
                      active ? "bg-accent/10 text-accent" : "bg-surface-3 text-foreground-muted"
                    }`}
                  >
                    {section.count}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
