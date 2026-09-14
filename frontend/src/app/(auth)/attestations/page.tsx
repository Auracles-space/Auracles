/**
 * Authenticated requestor Attestation workspace.
 */
import { Suspense } from "react";

import { RequestorPanel } from "@/components/modules/attestation/requestor-panel";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";

/**
 * Render requestor-side Attestation request and report controls.
 *
 * The panel reads the `target` query parameter to pin a framework, so it is
 * mounted inside a Suspense boundary as Next requires for `useSearchParams`.
 */
export default function AttestationsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <Suspense fallback={<TableSkeleton />}>
          <RequestorPanel />
        </Suspense>
      </div>
    </main>
  );
}
