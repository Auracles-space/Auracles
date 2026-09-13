/**
 * Authenticated admin attestor pipeline route.
 *
 * One page for applications, calibration trials, and fixtures. The console
 * reads `?tab=` so the old routes can redirect straight to the right tab.
 */
import type { Metadata } from "next";
import { Suspense } from "react";

import { AdminAttestorsConsole } from "@/components/modules/admin/attestors/admin-attestors-console";

export const metadata: Metadata = {
  title: "Attestors - Admin",
};

/**
 * Render the attestor console. Suspense satisfies `useSearchParams` in the
 * client console during static rendering.
 */
export default function AdminAttestorsPage() {
  return (
    <Suspense fallback={null}>
      <AdminAttestorsConsole />
    </Suspense>
  );
}
