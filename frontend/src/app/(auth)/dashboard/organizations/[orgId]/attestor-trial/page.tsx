import { TrialWorkspace } from "@/components/modules/organizations/attestor/trial-workspace";

export default async function OrgAttestorTrialPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  return <TrialWorkspace orgId={orgId} />;
}
