/**
 * Authenticated requestor Attestation workspace.
 */
import { RequestorPanel } from "@/components/modules/attestation/requestor-panel";

/**
 * Render requestor-side Attestation request and report controls.
 */
export default function AttestationsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <RequestorPanel />
      </div>
    </main>
  );
}
