/**
 * Contributor payout account settings route.
 */
import { PayoutAccountConnect } from "@/components/modules/financials/payout-account-connect";

/**
 * Render provider-hosted payout account onboarding and status.
 */
export default function PayoutAccountsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <PayoutAccountConnect />
      </div>
    </main>
  );
}
