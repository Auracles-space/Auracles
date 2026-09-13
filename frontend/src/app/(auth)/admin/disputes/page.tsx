/**
 * Authenticated admin dispute route.
 *
 * Attestation and Project disputes resolve here as two tabs of one console.
 */
import { Suspense } from "react";

import { AdminDisputesConsole } from "@/components/modules/admin/admin-disputes-console";

/**
 * Render the disputes console. Suspense satisfies `useSearchParams` during
 * static rendering.
 */
export default function AdminDisputesPage() {
  return (
    <Suspense fallback={null}>
      <AdminDisputesConsole />
    </Suspense>
  );
}
