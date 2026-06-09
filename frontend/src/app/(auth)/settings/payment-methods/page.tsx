/**
 * Operator payment method settings route.
 */
import { PaymentMethodList } from "@/components/modules/financials/payment-method-list";

/**
 * Render provider-held payment method management for Operators.
 */
export default function PaymentMethodsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <PaymentMethodList />
      </div>
    </main>
  );
}
