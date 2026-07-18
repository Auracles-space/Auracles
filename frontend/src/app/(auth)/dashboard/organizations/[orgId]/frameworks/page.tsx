/**
 * Organization Framework list route.
 *
 * Renders Frameworks authored under the selected organization identity.
 */
import Link from "next/link";
import { PlusIcon } from "@radix-ui/react-icons";

import { FrameworkList } from "@/components/modules/frameworks/framework-list";

type OrgFrameworksPageProps = {
  params: Promise<{ orgId: string }>;
};

/** Render the organization contributor's Framework list. */
export default async function OrgFrameworksPage({
  params,
}: OrgFrameworksPageProps) {
  const { orgId } = await params;
  const basePath = `/dashboard/organizations/${orgId}/frameworks`;

  return (
    <div className="min-w-0">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-heading text-2xl font-bold text-foreground">
            Frameworks
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Frameworks published under this organization.
          </p>
        </div>
        <Link
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-foreground px-5 py-2.5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent"
          href={`${basePath}/new`}
        >
          <PlusIcon className="h-4 w-4 stroke-[1.5]" />
          Create framework
        </Link>
      </div>
      <FrameworkList
        basePath={basePath}
        seller={{ kind: "org", orgId }}
      />
    </div>
  );
}
