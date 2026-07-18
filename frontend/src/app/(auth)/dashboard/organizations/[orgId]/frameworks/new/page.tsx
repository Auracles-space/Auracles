/**
 * Organization Framework creation route.
 *
 * Creates a Framework under the selected organization contributor identity.
 */
import { CreateFrameworkPanel } from "@/components/modules/frameworks/create-framework-panel";

type NewOrgFrameworkPageProps = {
  params: Promise<{ orgId: string }>;
};

/** Render the organization-scoped Framework creation form. */
export default async function NewOrgFrameworkPage({
  params,
}: NewOrgFrameworkPageProps) {
  const { orgId } = await params;

  return (
    <CreateFrameworkPanel
      basePath={`/dashboard/organizations/${orgId}/frameworks`}
      seller={{ kind: "org", orgId }}
    />
  );
}
