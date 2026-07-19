/**
 * Organization Project workspace route.
 *
 * Keeps organization-operated work inside the organization dashboard while
 * reusing the shared Project workspace with an explicit organization identity.
 */
import { Suspense } from "react";

import { ProjectWorkspace } from "@/components/modules/projects/project-workspace";

type OrgProjectPageProps = {
  params: Promise<{ id: string; orgId: string }>;
};

/** Render one organization-operated Project workspace. */
export default async function OrgProjectPage({ params }: OrgProjectPageProps) {
  const { id, orgId } = await params;
  return (
    <Suspense>
      <ProjectWorkspace
        mode={{ kind: "org", orgId }}
        projectId={id}
      />
    </Suspense>
  );
}
