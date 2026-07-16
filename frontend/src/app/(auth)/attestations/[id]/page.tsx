/**
 * Requestor Attestation detail route.
 */
import { AttestationDetail } from "@/components/modules/attestation/attestation-detail";

type AttestationDetailPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render the detail view for one Attestation request.
 *
 * @param props - Next.js route params.
 */
export default async function AttestationDetailPage({
  params,
}: AttestationDetailPageProps) {
  const { id } = await params;

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <AttestationDetail attestationId={id} />
      </div>
    </main>
  );
}
