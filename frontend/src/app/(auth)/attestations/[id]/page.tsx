/**
 * Requestor Attestation detail route.
 */
import { AttestationDetail } from "@/components/modules/attestation/attestation-detail";

type AttestationDetailPageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ funded?: string }>;
};

/**
 * Render the detail view for one Attestation request.
 *
 * @param props - Next.js route params; `funded=1` marks a return from hosted
 *   checkout (the Paystack callback URL), so the view confirms the payment.
 */
export default async function AttestationDetailPage({
  params,
  searchParams,
}: AttestationDetailPageProps) {
  const { id } = await params;
  const { funded } = await searchParams;

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <AttestationDetail attestationId={id} returningFromPayment={funded === "1"} />
      </div>
    </main>
  );
}
