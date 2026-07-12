import { OrgFinancialsTab } from "@/components/modules/organizations/operator/org-financials-tab";

export default async function OrgFinancialsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const resolvedParams = await params;
  return <OrgFinancialsTab orgId={resolvedParams.orgId} />;
}
