/**
 * Authenticated admin single-payment trace route.
 */
import { AdminPaymentTrace } from "@/components/modules/admin/admin-payment-trace";

type AdminPaymentTracePageProps = {
  params: Promise<{ transactionId: string }>;
};

/**
 * Render the ledger timeline for one payment.
 *
 * @param props - Route params carrying the transaction id.
 */
export default async function AdminPaymentTracePage({
  params,
}: AdminPaymentTracePageProps) {
  const { transactionId } = await params;
  return <AdminPaymentTrace transactionId={transactionId} />;
}
