/**
 * Authenticated admin payout-oversight route.
 */
import { AdminPayoutsPanel } from "@/components/modules/admin/admin-payouts-panel";
import { AdminSharedPayoutDestinationsPanel } from "@/components/modules/admin/admin-shared-payout-destinations-panel";

/**
 * Render the admin payout directory and the shared bank account review queue.
 *
 * The two belong together: the directory shows where money went, and the
 * shared-destination queue shows where several owners are being paid into one
 * account — the signal that distinguishes a sole trader from a payout funnel.
 */
export default function AdminPayoutsPage() {
  return (
    <div className="grid gap-8">
      <AdminPayoutsPanel />
      <AdminSharedPayoutDestinationsPanel />
    </div>
  );
}
