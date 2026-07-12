import { notFound } from "next/navigation";

import { OrgProjectsTab } from "@/components/modules/organizations/operator/org-projects-tab";

export default async function OrgProjectsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const resolvedParams = await params;
  if (!resolvedParams.orgId) {
    notFound();
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <OrgProjectsTab orgId={resolvedParams.orgId} />
    </div>
  );
}
