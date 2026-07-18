/**
 * Organization Framework list route.
 *
 * Renders Frameworks authored under the selected organization identity.
 */
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
      <div className="mb-6">
        <h2 className="font-heading text-2xl font-bold text-foreground">
          Frameworks
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Frameworks published under this organization.
        </p>
      </div>
      <FrameworkList
        basePath={basePath}
        seller={{ kind: "org", orgId }}
      />
    </div>
  );
}
