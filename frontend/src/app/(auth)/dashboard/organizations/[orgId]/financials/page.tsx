import { OrgAttestorFinancialsTab } from "@/components/modules/organizations/attestor/org-attestor-financials-tab";

export default async function OrgFinancialsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const resolvedParams = await params;
  return <OrgAttestorFinancialsTab orgId={resolvedParams.orgId} />;
}
