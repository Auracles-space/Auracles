import { AttestationWorkspace } from "@/components/modules/organizations/attestor/workspace/attestation-workspace";

export default async function AttestationWorkspacePage({
  params,
}: {
  params: Promise<{ orgId: string; attestationId: string }>;
}) {
  const resolvedParams = await params;
  return (
    <div className="p-4 sm:p-6 md:p-8">
      <AttestationWorkspace orgId={resolvedParams.orgId} attestationId={resolvedParams.attestationId} />
    </div>
  );
}
